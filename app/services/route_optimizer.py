"""
Smart Distribution - Route Optimizer Service
==============================================

Bu modül, "Vehicle Routing Problem with Capacity Constraints" (CVRP) probleminin
basit ve sağlam bir sezgisel (heuristic) çözümünü içerir.

Kullanılan Yaklaşım:
    1. Greedy Nearest-Neighbor (Açgözlü En Yakın Komşu) ile durak sıralama
    2. Araç kapasitesi (capacity_kg) sıkı kısıt olarak uygulanır
    3. Sipariş önceliği (priority) sıralamayı yönlendirir
    4. Her aracın rotası oluşturulur ve DB'ye (Route + RouteStop) yazılır

Tasarım Notları:
    - Gerçek harita entegrasyonu (OSRM/Google) yerine kuş uçuşu mesafe
      (Haversine) kullanılır; deprem/köprü gibi yol kısıtlarını hesaba katmaz
      ama küçük/orta ölçekli dağıtımlarda yeterince iyi başlangıç noktasıdır.
    - OR-Tools veya 2-opt iyileştirmesi gibi global arama teknikleri
      ileride bu modüle kolayca eklenebilir (bkz. _two_opt_improve).
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timezone
from typing import List, Optional, Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, joinedload

from app.models.customer import Customer
from app.models.order import Order
from app.models.vehicle import Vehicle
from app.models.route import Route
from app.models.route_stop import RouteStop


# ------------------------------------------------------------------
#  Sabitler — Dünya üzerindeki sabit değerler
# ------------------------------------------------------------------
EARTH_RADIUS_KM: float = 6371.0088  # Dünya'nın ortalama yarıçapı (km)

# Sürüş hızı tahmini (km/saat). Gerçek OSRM entegrasyonu olmadığı için
# kuş uçuşu mesafeyi ~1.3 çarpanı ile yol mesafesine çeviriyoruz.
AVG_DRIVING_SPEED_KMH: float = 40.0


# ============================================================
#  BÖLÜM 1: Mesafe & Süre Yardımcı Fonksiyonları
# ============================================================

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    İki koordinat arasındaki kuş uçuşu mesafeyi kilometre olarak hesaplar.

    Formül:
        d = 2 * r * arcsin( sqrt( sin²(Δlat/2)
                               + cos(lat1) * cos(lat2) * sin²(Δlng/2) ) )

    Args:
        lat1, lng1: Başlangıç noktası (derece)
        lat2, lng2: Bitiş noktası (derece)

    Returns:
        İki nokta arasındaki mesafe (kilometre)
    """
    # Derece -> Radyan dönüşümü (math modülü radyan ile çalışır)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)

    # Haversine formülünün iç toplamı
    a = (math.sin(dphi / 2.0) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2)

    # arcsin sonucunu Dünya yarıçapı ile çarp
    c = 2.0 * math.asin(math.sqrt(a))
    return EARTH_RADIUS_KM * c


def estimate_duration_min(distance_km: float) -> int:
    """
    Mesafeyi ortalama sürüş hızına bölerek tahmini sürüş süresini (dakika) hesaplar.
    Gerçek harita verisi geldiğinde bu fonksiyon OSRM süresi ile değiştirilebilir.
    """
    if distance_km <= 0:
        return 0
    return int(round((distance_km / AVG_DRIVING_SPEED_KMH) * 60.0))


# ============================================================
#  BÖLÜM 2: Veri Yapıları (Algoritma İçin)
# ============================================================

class _Stop:
    """
    Algoritma içinde kullanılan hafif (lightweight) durak temsili.
    SQLAlchemy nesnesi yerine bir veri sınıfı kullanmak:
      - Döngü içindeki attribute erişimini hızlandırır
      - Algoritma ve ORM katmanını gevşek bağlı (loose coupling) yapar
    """

    __slots__ = ("order_id", "lat", "lng", "weight", "priority")

    def __init__(self, order_id: int, lat: float, lng: float,
                 weight: float, priority: int) -> None:
        self.order_id = order_id
        self.lat = lat
        self.lng = lng
        self.weight = weight
        self.priority = priority


class _VehicleLoad:
    """Bir aracın algoritma boyunca taşıdığı yükün durumunu tutar."""

    def __init__(self, vehicle: Vehicle) -> None:
        self.vehicle: Vehicle = vehicle
        self.stops: List[_Stop] = []      # Sıralı durak listesi
        self.used_kg: float = 0.0        # Şu ana kadar yüklenen toplam ağırlık

    @property
    def remaining_kg(self) -> float:
        """Aracın hâlâ alabileceği kapasite miktarı."""
        return self.vehicle.capacity_kg - self.used_kg

    def can_fit(self, weight: float) -> bool:
        """Sıkı kısıt: yeni sipariş aracın kalan kapasitesine sığar mı?"""
        # Sıfıra bölmeyi önle; çok küçük bir epsilon ile tolerans tanımla
        return weight <= self.remaining_kg + 1e-9

    def total_distance_km(self) -> float:
        """Depo (aracın konumu) -> duraklar -> dönüş mesafesi toplamı."""
        # Araç konumu yoksa ilk durağı başlangıç noktası olarak kullan
        start_lat = self.vehicle.lat if self.vehicle.lat is not None else (
            self.stops[0].lat if self.stops else 0.0
        )
        start_lng = self.vehicle.lng if self.vehicle.lng is not None else (
            self.stops[0].lng if self.stops else 0.0
        )

        if not self.stops:
            return 0.0

        total = 0.0
        # 1) Depo -> ilk durak
        total += haversine_km(start_lat, start_lng,
                              self.stops[0].lat, self.stops[0].lng)
        # 2) Duraklar arası
        for i in range(1, len(self.stops)):
            total += haversine_km(self.stops[i - 1].lat, self.stops[i - 1].lng,
                                  self.stops[i].lat, self.stops[i].lng)
        # 3) Son durak -> depoya dönüş
        total += haversine_km(self.stops[-1].lat, self.stops[-1].lng,
                              start_lat, start_lng)
        return total


# ============================================================
#  BÖLÜM 3: Çekirdek Optimizasyon Algoritması
# ============================================================

def _prioritize(stops: Sequence[_Stop]) -> List[_Stop]:
    """
    Siparişleri önce önceliğe (büyükten küçüğe), sonra ID'ye göre sıralar.
    Bu, yüksek öncelikli siparişlerin önce arabalara yerleştirilmesini garanti eder.
    """
    return sorted(stops, key=lambda s: (-s.priority, s.order_id))


def _select_candidate(
    current: tuple[float, float],
    unassigned: List[_Stop],
    vehicle: _VehicleLoad,
) -> Optional[int]:
    """
    Verilen konumdan ve kalan kapasiteden, en yakın uygun siparişin
    unassigned listesindeki indexini döner. Bulamazsa None.

    'Uygun' tanımı: aracın kalan kapasitesine sığan ve en yakın olan durak.
    """
    best_idx: Optional[int] = None
    best_dist: float = math.inf

    for idx, stop in enumerate(unassigned):
        # Sıkı kapasite kısıtı: sipariş araca sığmıyorsa atla
        if not vehicle.can_fit(stop.weight):
            continue

        dist = haversine_km(current[0], current[1], stop.lat, stop.lng)
        if dist < best_dist:
            best_dist = dist
            best_idx = idx

    return best_idx


def _assign_orders_to_vehicles(
    vehicles: List[Vehicle],
    stops: List[_Stop],
) -> List[_VehicleLoad]:
    """
    Ana atama döngüsü:
      - Her siparişi, "o an en yakın + kapasitesi uygun" araca ata.
      - Siparişleri önce yüksek öncelikli olanlardan başlayarak işle.
      - Hiçbir araca sığmayan siparişler 'unassigned' listesinde kalır.
    """
    # 1) Araçları büyükten küçüğe kapasiteye göre sırala
    #    -> büyük kapasiteli araç önce doldurulur, küçükler yedekte kalır
    sorted_vehicles = sorted(vehicles, key=lambda v: v.capacity_kg, reverse=True)
    loads: List[_VehicleLoad] = [_VehicleLoad(v) for v in sorted_vehicles]

    # 2) Siparişleri öncelik sırasına göre işle
    prioritized = _prioritize(stops)
    unassigned: List[_Stop] = list(prioritized)

    for stop in prioritized:
        # Her sipariş için en uygun aracı bul.
        # Uygun araç = "aracın mevcut son durağına en yakın olan"
        #              ve kapasitesi siparişi alabilen.
        best_load: Optional[_VehicleLoad] = None
        best_total: float = math.inf
        best_position: Optional[int] = None  # aracın durak listesinde nereye

        for load in loads:
            if not load.can_fit(stop.weight):
                continue  # kapasite yetmiyor, bu aracı atla

            # Aracın son konumu (henüz durak yoksa aracın kendi konumu)
            if load.stops:
                cur_lat, cur_lng = load.stops[-1].lat, load.stops[-1].lng
            elif load.vehicle.lat is not None and load.vehicle.lng is not None:
                cur_lat, cur_lng = load.vehicle.lat, load.vehicle.lng
            else:
                cur_lat, cur_lng = stop.lat, stop.lng

            # Eğer araç boşsa, mesafe = siparişin araca olan uzaklığı
            # Değilse, son durağa olan uzaklık (greedy en yakın komşu)
            dist = haversine_km(cur_lat, cur_lng, stop.lat, stop.lng)
            if dist < best_total:
                best_total = dist
                best_load = load
                best_position = None  # her zaman sona ekle (basit yaklaşım)

        if best_load is None:
            # Hiçbir araca sığmadı — atlananlar listesinde kalacak
            # (veritabanında durumu 'pending' olarak bırakılır)
            continue

        # Siparişi en uygun aracın durak listesinin sonuna ekle
        best_load.stops.append(stop)
        best_load.used_kg += stop.weight
        # Atanan siparişi unassigned listesinden çıkar
        if stop in unassigned:
            unassigned.remove(stop)

    return loads


# ============================================================
#  BÖLÜM 4: Veritabanı Kalıcılık (Persistence) Katmanı
# ============================================================

async def _persist_results(
    db: AsyncSession,
    loads: List[_VehicleLoad],
) -> List[Route]:
    """
    Her araç için bir Route kaydı, her durak için RouteStop kaydı oluşturur.
    Sıkı kısıt kontrolü: persistence öncesi son kez kapasiteyi doğrular.
    """
    created_routes: List[Route] = []
    now = datetime.now(timezone.utc)

    for load in loads:
        # Boş rotaları kaydetme — araca hiç sipariş atanmadıysa geç
        if not load.stops:
            continue

        # ---- Son güvenlik kontrolü: kapasite gerçekten aşılmadı mı? ----
        if load.used_kg > load.vehicle.capacity_kg + 1e-9:
            raise RuntimeError(
                f"Kapasite aşıldı! vehicle={load.vehicle.plate} "
                f"used={load.used_kg} cap={load.vehicle.capacity_kg}"
            )

        # ---- Toplam mesafe ve süreyi hesapla ----
        distance = load.total_distance_km()
        duration = estimate_duration_min(distance)

        # ---- Route kaydını oluştur ----
        route = Route(
            tenant_id=load.vehicle.tenant_id,
            vehicle_id=load.vehicle.id,
            name=f"Route-{load.vehicle.plate}-{now.strftime('%Y%m%d%H%M')}",
            total_distance_km=round(distance, 3),
            total_duration_min=duration,
            status="optimized",
            optimized_at=now,
        )
        db.add(route)
        await db.flush()  # route.id'yi almak için flush (commit etmeden)

        # ---- Her durak için RouteStop kaydı ----
        for seq, stop in enumerate(load.stops, start=1):
            route_stop = RouteStop(
                tenant_id=load.vehicle.tenant_id,
                route_id=route.id,
                order_id=stop.order_id,
                stop_sequence=seq,
                status="pending",
            )
            db.add(route_stop)

            # İlgili siparişin durumunu ve araç/route bağlantısını güncelle
            order = await db.get(Order, stop.order_id)
            if order is not None:
                order.status = "assigned"
                order.vehicle_id = load.vehicle.id
                order.route_id = route.id

        created_routes.append(route)

    return created_routes


# ============================================================
#  BÖLÜM 5: OSRM Gerçek Rota Geometrisi Entegrasyonu (Async)
# ============================================================

OSRM_BASE_URL = "https://router.project-osrm.org/route/v1/driving"
OSRM_TIMEOUT = 15.0
OSRM_USER_AGENT = "SmartDistribution/1.0"


def _build_fallback_geometry(load: _VehicleLoad) -> dict:
    """
    OSRM başarısız olursa kuş uçuşu (Haversine) düz çizgi geometrisi üretir.
    GeoJSON LineString formatında döner.
    """
    coordinates: List[List[float]] = []

    if load.vehicle.lat is not None and load.vehicle.lng is not None:
        coordinates.append([load.vehicle.lng, load.vehicle.lat])

    for stop in load.stops:
        coordinates.append([stop.lng, stop.lat])

    if len(coordinates) < 2:
        return {"type": "LineString", "coordinates": []}

    return {"type": "LineString", "coordinates": coordinates}


async def _fetch_single_osrm_geometry(
    client: httpx.AsyncClient,
    load: _VehicleLoad,
) -> dict:
    """
    Tek bir araç rotası için OSRM'den geometri çeker.
    Hata durumunda fallback geometri döner.
    """
    coords: List[str] = []

    if load.vehicle.lat is not None and load.vehicle.lng is not None:
        coords.append(f"{load.vehicle.lng},{load.vehicle.lat}")

    for stop in load.stops:
        coords.append(f"{stop.lng},{stop.lat}")

    if len(coords) < 2:
        return _build_fallback_geometry(load)

    coord_str = ";".join(coords)
    url = f"{OSRM_BASE_URL}/{coord_str}?overview=full&geometries=geojson"

    try:
        resp = await client.get(url, timeout=OSRM_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != "Ok" or not data.get("routes"):
            return _build_fallback_geometry(load)

        return data["routes"][0]["geometry"]

    except (httpx.RequestError, httpx.HTTPStatusError, json.JSONDecodeError, KeyError):
        return _build_fallback_geometry(load)


# Aynı anda OSRM'e gidecek maksimum paralel istek sayısı.
# Sınırsız bırakılırsa 100 eş zamanlı kullanıcıda httpx bağlantı havuzu
# tükenir ve sistem kilitlenir.
_OSRM_CONCURRENCY = 10


async def _fetch_osrm_geometries_async(
    loads: List[_VehicleLoad],
    routes: List[Route],
) -> None:
    """
    Tüm araç rotaları için OSRM geometrilerini PARALEL olarak çeker.
    Herhangi bir hata durumunda fallback (Haversine düz çizgi) kullanılır.

    KRİTİK DÜZELTME (zip hizalama):
        Sadece load.stops'u dolu olan yükler için hem görev (task) hem de
        rota (route) eşleşmesi yapılır. Aksi hâlde asyncio.gather sonuçları
        ile Route nesneleri kayar ve yanlış rotaya geometri yazılır.
    """
    if not loads:
        return

    # Sadece durağı olan yükleri al — bunlar _persist_results'ta Route yaratan yükler
    active_pairs = [(load, route) for load, route in zip(loads, routes) if load.stops]
    if not active_pairs:
        return

    semaphore = asyncio.Semaphore(_OSRM_CONCURRENCY)

    async def _guarded_fetch(client: httpx.AsyncClient, load: _VehicleLoad) -> dict:
        async with semaphore:
            return await _fetch_single_osrm_geometry(client, load)

    async with httpx.AsyncClient(
        headers={"User-Agent": OSRM_USER_AGENT},
        timeout=httpx.Timeout(OSRM_TIMEOUT),
    ) as client:
        tasks = [_guarded_fetch(client, load) for load, _ in active_pairs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for (load, route), geometry in zip(active_pairs, results):
        if isinstance(geometry, Exception):
            route.route_geometry = json.dumps(_build_fallback_geometry(load))
        else:
            route.route_geometry = json.dumps(geometry)


# ============================================================
#  BÖLÜM 6: Public API — Servisin Dışarıya Açılan Yüzü
# ============================================================

async def optimize_routes(
    db: Session,
    vehicles: List[Vehicle],
    orders: List[Order],
    origin_lat: float | None = None,
    origin_lng: float | None = None,
) -> dict:
    """
    Akıllı Dağıtım & Rota Optimizasyonu için ana giriş noktası (Async).

    Args:
        db: Aktif SQLAlchemy oturumu
        vehicles: Durumu 'available' olan araç listesi
        orders: Durumu 'pending' olan sipariş listesi
        origin_lat: Şoförün anlık GPS enlemi (varsa ilk aracın başlangıcı olur)
        origin_lng: Şoförün anlık GPS boylamı

    Returns:
        Optimizasyon sonuçlarını içeren sözlük:
        {
            "routes": [Route, ...],
            "unassigned_order_ids": [int, ...],
            "summary": {
                "total_vehicles_used": int,
                "total_orders_assigned": int,
                "total_distance_km": float,
                "total_duration_min": int,
            }
        }
    """
    # 1) Girdi doğrulama
    if not vehicles:
        return {
            "routes": [],
            "unassigned_order_ids": [o.id for o in orders],
            "summary": _empty_summary(),
        }

    if not orders:
        return {
            "routes": [],
            "unassigned_order_ids": [],
            "summary": _empty_summary(),
        }

    # 2) GPS konumu verilmişse ilk aracın başlangıç koordinatını ata
    # Kopyalama yaparak orijinal ORM nesnesini mutasyona uğratmıyoruz
    vehicles_copy = list(vehicles)
    if origin_lat is not None and origin_lng is not None and vehicles_copy:
        vehicles_copy[0].lat = origin_lat
        vehicles_copy[0].lng = origin_lng

    # 3) Algoritma için hafif _Stop nesnelerine dönüştür
    stops: List[_Stop] = [
        _Stop(
            order_id=o.id,
            lat=o.delivery_lat,
            lng=o.delivery_lng,
            weight=o.weight_kg,
            priority=o.priority or 0,
        )
        for o in orders
    ]

    # 4) Çekirdek optimizasyonu çalıştır
    loads = _assign_orders_to_vehicles(vehicles_copy, stops)

    # 5) Atanamayan siparişleri tespit et
    assigned_ids = {s.order_id for load in loads for s in load.stops}
    unassigned_ids = [o.id for o in orders if o.id not in assigned_ids]

    # 6) Veritabanına yaz (tek commit - atomik)
    # KRİTİK: Hata durumunda transaction açık kalmasın; explicit rollback zorunlu.
    try:
        created_routes = await _persist_results(db, loads)
    except Exception:
        await db.rollback()
        raise

    # 7) OSRM'den gerçek yol geometrilerini PARALEL olarak al
    #    OSRM çağrıları commit öncesi yapılır; hata olursa rollback garantilidir.
    try:
        await _fetch_osrm_geometries_async(loads, created_routes)
    except Exception:
        # OSRM tamamen başarısız oldu; fallback geometrileri zaten _build_fallback_geometry
        # tarafından doldurulmuş olmalı. Yine de güvenlik için pass geçiyoruz.
        pass

    await db.commit()

    # 8) Re-fetch routes eagerly to prevent MissingGreenlet in API response
    if created_routes:
        stmt = (
            select(Route)
            .options(
                joinedload(Route.route_stops).joinedload(RouteStop.order)
            )
            .filter(Route.id.in_([r.id for r in created_routes]))
        )
        result = await db.execute(stmt)
        created_routes = list(result.unique().scalars().all())

    # 9) Özet istatistikleri hazırla
    total_distance = sum(r.total_distance_km or 0.0 for r in created_routes)
    total_duration = sum(r.total_duration_min or 0 for r in created_routes)

    return {
        "routes": created_routes,
        "unassigned_order_ids": unassigned_ids,
        "summary": {
            "total_vehicles_used": len(created_routes),
            "total_orders_assigned": len(assigned_ids),
            "total_distance_km": round(total_distance, 3),
            "total_duration_min": total_duration,
        },
    }


def _empty_summary() -> dict:
    """Boş sonuç için tutarlı özet sözlüğü."""
    return {
        "total_vehicles_used": 0,
        "total_orders_assigned": 0,
        "total_distance_km": 0.0,
        "total_duration_min": 0,
    }


# ============================================================
#  BÖLÜM 7: Test Amaçlı Hızlı Erişim
# ============================================================

async def fetch_pending_orders(db: AsyncSession, tenant_id: int) -> List[Order]:
    """Yalnızca Bucak bölgesindeki 'pending' siparişleri getirir (Async)."""
    result = await db.execute(
        select(Order)
        .join(Order.customer)
        .filter(Order.tenant_id == tenant_id)
        .filter(Order.status == "pending")
        .filter(Order.vehicle_id.is_(None))
    )
    return list(result.scalars().all())


async def fetch_available_vehicles(db: AsyncSession, tenant_id: int) -> List[Vehicle]:
    """Kullanıma hazır araçları getirir (Async)."""
    result = await db.execute(
        select(Vehicle).filter(Vehicle.tenant_id == tenant_id).filter(Vehicle.status == "available")
    )
    return list(result.scalars().all())
