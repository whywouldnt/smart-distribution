'use strict';

/* ══════════════════════════════════════════════════════════
   CONFIG & STATE
══════════════════════════════════════════════════════════ */
const BASE = '/api/v1';

// Global error handler
window.onerror = function(msg, url, line, col, err) {
    console.error(`[Global Error] ${msg} at ${url}:${line}:${col}`, err);
    toast(`❌ Hata: ${msg.substring(0, 80)}`, false);
    return false;
};

window.addEventListener('unhandledrejection', event => {
    console.error('[Unhandled Promise Rejection]', event.reason);
    toast(`❌ Hata: ${String(event.reason).substring(0, 80)}`, false);
});

const COLORS = ['#2f81f7','#3fb950','#f0883e','#a371f7','#ec4899','#22d3ee','#fbbf24','#f87171'];
const VEH_TYPE = { van:'Van', truck:'Kamyon', motorcycle:'Motorsiklet', bicycle:'Bisiklet' };
const STATUS_L = { available:'Müsait', in_use:'Seferde', maintenance:'Bakımda' };

let routeLayers = [];
let custMarkers = {};   // id → marker
let mapFilter   = 'all';
let currentBTab = 'info';

// Driver mode state
let dmRoute     = null; // full route from API
let dmStopIdx   = 0;    // current stop index (0-based)
let dmReturns   = 0;    // actual empty returns counter
let _tt;                // toast timeout identifier

/* ══════════════════════════════════════════════════════════
   AUTH & XSS
══════════════════════════════════════════════════════════ */
function esc(v) {
    if (v == null) return '';
    return String(v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
                    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

let token = localStorage.getItem('token');

async function authFetch(url, options = {}) {
    if (!options.headers) options.headers = {};
    if (token) options.headers['Authorization'] = `Bearer ${token}`;
    
    const res = await fetch(url, options);
    if (res.status === 401) {
        // Unauthorized, show login
        document.getElementById('loginOverlay').style.display = 'flex';
        token = null;
        localStorage.removeItem('token');
        throw new Error("Unauthorized");
    }
    return res;
}

async function doLogin() {
    const email = document.getElementById('logEmail').value;
    const pass = document.getElementById('logPass').value;
    if (!email || !pass) { toast('Lütfen e-posta ve şifre girin', false); return; }
    
    loading(true, 'Giriş yapılıyor...');
    try {
        const formData = new FormData();
        formData.append('username', email);
        formData.append('password', pass);
        
        const r = await fetch(`${BASE}/auth/login`, {
            method: 'POST',
            body: formData
        });
        
        if (!r.ok) {
            console.warn('[doLogin] Login failed with status:', r.status);
            let errMsg = 'Giriş başarısız. Lütfen e-posta ve şifrenizi kontrol edin.';
            try {
                const errData = await r.json();
                if (errData.detail) errMsg = errData.detail;
            } catch(_) {}
            throw new Error(errMsg);
        }
        
        const data = await r.json();
        if (!data.access_token) throw new Error('API yanıtında token bulunamadı');
        
        token = data.access_token;
        localStorage.setItem('token', token);
        console.log('[doLogin] Login successful');
        
        document.getElementById('loginOverlay').style.display = 'none';
        toast('Giriş başarılı! 🎉', true);
        
        // Load initial data
        loadDashboard();
    } catch (e) {
        console.error('[doLogin] Error:', e.message);
        toast(e.message || 'Bağlantı hatası', false);
    } finally {
        loading(false);
    }
}

function doLogout() {
    token = null;
    localStorage.removeItem('token');
    document.getElementById('loginOverlay').style.display = 'flex';
    document.getElementById('logPass').value = '';
}

// Initial check
if (!token) {
    document.getElementById('loginOverlay').style.display = 'flex';
} else {
    document.getElementById('loginOverlay').style.display = 'none';
}

/* ══════════════════════════════════════════════════════════
   MAP
══════════════════════════════════════════════════════════ */
let map = null;

function initMap() {
    if (map) return; // Already initialized
    map = L.map('map', { zoomControl: true }).setView([37.455834, 30.587761], 14.5);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '© <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(map);
    setTimeout(() => map.invalidateSize(), 350);

    map.on('click', e => {
        const cLatEl = document.getElementById('cLat');
        const cLngEl = document.getElementById('cLng');
        if (cLatEl) cLatEl.value = e.latlng.lat.toFixed(6);
        if (cLngEl) cLngEl.value = e.latlng.lng.toFixed(6);
    });
}

function custIcon(initials) {
    return L.divIcon({
        html: `<div style="background:#3fb950;color:#0d1117;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;border:2px solid #0d1117;box-shadow:0 2px 8px rgba(0,0,0,.5);">${esc(initials)}</div>`,
        className: '', iconSize: [32,32], iconAnchor: [16,16]
    });
}
function stopIcon(n, color) {
    return L.divIcon({
        html: `<div style="background:${color};color:#fff;width:26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;border:2px solid #0d1117;box-shadow:0 2px 6px rgba(0,0,0,.5);">${n}</div>`,
        className: '', iconSize: [26,26], iconAnchor: [13,13]
    });
}
function popupHtml(title, sub, stats=[], lat, lng) {
    const sl = stats.map(([k,v]) => `<div class="popup-stat"><span>${esc(k)}</span><span>${esc(String(v))}</span></div>`).join('');
    return `<div class="popup-inner">
        <div class="popup-title">${esc(title)}</div>
        <div class="popup-sub">${esc(sub)}</div>
        ${sl}
        <button class="popup-navbtn" onclick="nav(${lat},${lng})">📍 Navigasyonu Başlat</button>
    </div>`;
}

function setFilter(f) {
    mapFilter = f;
    ['all','customers','routes'].forEach(k => {
        const id = {all:'pAll',customers:'pCus',routes:'pRou'}[k];
        const el = document.getElementById(id);
        if (el) el.classList.toggle('on', k === f);
    });
    if (map) {
        Object.values(custMarkers).forEach(m => f === 'routes' ? map.removeLayer(m) : (map.hasLayer(m) || m.addTo(map)));
        routeLayers.forEach(l => f === 'customers' ? map.removeLayer(l) : (map.hasLayer(l) || l.addTo(map)));
    }
}

/* ══════════════════════════════════════════════════════════
   NAVIGATION (iOS / Android)
══════════════════════════════════════════════════════════ */
function nav(lat, lng) {
    const isIOS = /iPhone|iPad|iPod/i.test(navigator.userAgent);
    const label = encodeURIComponent('Teslimat');
    if (isIOS) {
        window.location.href = `maps://?daddr=${lat},${lng}`;
        setTimeout(() => { window.location.href = `https://maps.apple.com/?daddr=${lat},${lng}`; }, 500);
    } else {
        window.location.href = `geo:${lat},${lng}?q=${lat},${lng}(${label})`;
        setTimeout(() => { if (document.hasFocus()) window.open(`https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`,'_blank'); }, 500);
    }
}

/* ══════════════════════════════════════════════════════════
   TOAST
══════════════════════════════════════════════════════════ */

function toast(msg, ok=true) {
    const el = document.getElementById('toast');
    document.getElementById('tmsg').textContent = msg;
    el.className = ok ? 'vis tok' : 'vis terr';
    clearTimeout(_tt);
    _tt = setTimeout(() => el.classList.remove('vis'), 3500);
}

/* ══════════════════════════════════════════════════════════
   LOADING
══════════════════════════════════════════════════════════ */
function loading(on, txt='Yükleniyor...') {
    const el = document.getElementById('loadingOverlay');
    document.getElementById('ltext').textContent = txt;
    el.style.display = on ? 'flex' : 'none';
}

/* ══════════════════════════════════════════════════════════
   DESKTOP PANEL TOGGLES
══════════════════════════════════════════════════════════ */
function toggleSidebar() {
    const el = document.getElementById('sidebar');
    const btn = document.getElementById('hbSidebar');
    el.classList.toggle('hidden');
    btn.classList.toggle('on', !el.classList.contains('hidden'));
    if (map) setTimeout(() => map.invalidateSize(), 320);
}
function toggleRoutes() {
    const el = document.getElementById('rpanel');
    const btn = document.getElementById('hbRoutes');
    el.classList.toggle('hidden');
    btn.classList.toggle('on', !el.classList.contains('hidden'));
    if (map) setTimeout(() => map.invalidateSize(), 320);
}

/* ══════════════════════════════════════════════════════════
   DESKTOP TABS
══════════════════════════════════════════════════════════ */
function switchTab(name) {
    const ids = ['customers','orders','vehicles','add'];
    document.querySelectorAll('.stab').forEach((b,i) => b.classList.toggle('on', ids[i] === name));
    ids.forEach(id => {
        const p = document.getElementById('sp-'+id);
        if (p) p.classList.toggle('on', id === name);
    });
}

/* ══════════════════════════════════════════════════════════
   BOTTOM SHEET (Mobile)
══════════════════════════════════════════════════════════ */
let bsOpen = false;
let bsStartY = 0;
let bsCurrentY = 0;
const BS_SNAP_CLOSED = window.innerHeight * 0.9;

function openSheet(tab) {
    const bs = document.getElementById('bsheet');
    bsOpen = true;
    bs.style.transform = 'translateY(0)';
    ['mbInfo','mbRoutes','mbAdd'].forEach(id => if(document.getElementById(id)) document.getElementById(id).classList.remove('on'));
    const map = {info:'mbInfo', routes:'mbRoutes', add:'mbAdd'};
    if(document.getElementById(map[tab])) document.getElementById(map[tab]).classList.add('on');
    switchBTab(tab);
}

function closeSheet() {
    const bs = document.getElementById('bsheet');
    bsOpen = false;
    bs.style.transform = `translateY(${BS_SNAP_CLOSED}px)`;
}

function switchBTab(tab) {
    currentBTab = tab;
    document.querySelectorAll('.bstab').forEach((b,i) => {
        const tabs = ['info','routes','add'];
        b.classList.toggle('on', tabs[i] === tab);
    });
    const body = document.getElementById('bsbody');
    body.innerHTML = '';
    if (tab === 'info') renderInfoSheet(body);
    else if (tab === 'routes') renderRoutesSheet(body);
    else if (tab === 'add') renderAddSheet(body);
}

// Bottom sheet swipe
const bsh = document.getElementById('bsheet');
const handle = document.getElementById('bshHandle');

handle.addEventListener('pointerdown', e => {
    bsStartY = e.clientY;
    bsh.style.transition = 'none';
    handle.setPointerCapture(e.pointerId);
});
handle.addEventListener('pointermove', e => {
    const dy = e.clientY - bsStartY;
    if (dy > 0) bsh.style.transform = `translateY(${dy}px)`;
});
handle.addEventListener('pointerup', e => {
    bsh.style.transition = '';
    const dy = e.clientY - bsStartY;
    if (dy > 120) closeSheet();
    else bsh.style.transform = 'translateY(0)';
});

// Initialize bottom sheet as partially visible
window.addEventListener('load', () => {
    bsh.style.transform = `translateY(${window.innerHeight * 0.72}px)`;
});

/* ══════════════════════════════════════════════════════════
   DASHBOARD DATA
══════════════════════════════════════════════════════════ */
async function loadStats() {
    try {
        const r = await authFetch(`${BASE}/dashboard/stats`);
        if (!r.ok) return;
        const d = await r.json();
        document.getElementById('kA').textContent = d.total_customers;
        document.getElementById('kS').textContent = d.pending_orders;
        document.getElementById('kV').textContent = d.available_vehicles;
        document.getElementById('kD').textContent = d.total_bottles_pending;
    } catch(_) {}
}

let _custData = [];
async function loadCustomers() {
    try {
        const r = await authFetch(`${BASE}/dashboard/customers`);
        if (!r.ok) return;
        _custData = await r.json();
        renderCustomerList(document.getElementById('custList'), _custData);
        // Add map markers
        if (map) {
            _custData.forEach(c => {
                if (!custMarkers[c.id]) {
                    const ini = c.name.split(' ').map(w=>w[0]).slice(0,2).join('').toUpperCase();
                    const m = L.marker([c.lat,c.lng], {icon:custIcon(ini)}).addTo(map);
                    m.bindPopup(popupHtml(c.name, c.address, [['Bekleyen',c.pending_orders+' sipariş']], c.lat, c.lng));
                    custMarkers[c.id] = m;
                }
            });
        }
    } catch(e) { console.error(e); }
}

function renderCustomerList(container, list) {
    if (!list.length) {
        container.innerHTML = `<div class="empty"><div class="ei">👥</div><div class="et">Abone yok</div><div class="es">Ekle sekmesinden abone oluşturun.</div></div>`;
        return;
    }
    const countEl = document.getElementById('sh-custcount');
    if (countEl) countEl.textContent = list.length;
    container.innerHTML = '';
    list.forEach(c => {
        const ini = c.name.split(' ').map(w=>w[0]).slice(0,2).join('').toUpperCase();
        const el = document.createElement('div');
        el.className = 'li fup';
        el.innerHTML = `
            <div class="lavt" style="background:var(--green-dim);color:var(--green)">${esc(ini)}</div>
            <div class="lbody"><div class="ltitle">${esc(c.name)}</div><div class="lsub">${esc(c.address)}</div></div>
            ${c.pending_orders ? `<span class="badge bg-y">${esc(String(c.pending_orders))}</span>` : ''}
        `;
        el.onclick = () => { map.setView([c.lat,c.lng],16); if(custMarkers[c.id]) custMarkers[c.id].openPopup(); if (bsOpen) closeSheet(); };
        container.appendChild(el);
    });
}

let _orderData = [];
async function loadOrders() {
    try {
        const r = await authFetch(`${BASE}/dashboard/orders`);
        if (!r.ok) return;
        _orderData = await r.json();
        renderOrderList(document.getElementById('orderList'), _orderData);
    } catch(e) {}
}
function renderOrderList(container, list) {
    if (!list.length) {
        container.innerHTML = `<div class="empty"><div class="ei">📦</div><div class="et">Bekleyen sipariş yok</div></div>`;
        return;
    }
    container.innerHTML = '';
    list.forEach(o => {
        const el = document.createElement('div');
        el.className = 'li fup';
        const p = o.priority >= 2 ? '🔴' : o.priority === 1 ? '🟡' : '🟢';
        el.innerHTML = `
            <div class="lavt" style="background:var(--amber-dim);color:var(--amber);font-size:20px">💧</div>
            <div class="lbody">
                <div class="ltitle">${esc(o.customer_name||'#'+o.id)}</div>
                <div class="lsub">${esc(String(o.bottle_count))} dolu · ${esc(String(o.empty_returns_expected))} iade · ${esc(o.delivery_address)}</div>
            </div>
            <span class="badge bg-y">${p}</span>
        `;
        container.appendChild(el);
    });
}

let _vehData = [];
async function loadVehicles() {
    try {
        const r = await authFetch(`${BASE}/dashboard/vehicles`);
        if (!r.ok) return;
        _vehData = await r.json();
        renderVehicleList(document.getElementById('vehList'), _vehData);
    } catch(e) {}
}
function renderVehicleList(container, list) {
    if (!list.length) {
        container.innerHTML = `<div class="empty"><div class="ei">🚛</div><div class="et">Araç eklenmemiş</div></div>`;
        return;
    }
    container.innerHTML = '';
    list.forEach(v => {
        const el = document.createElement('div');
        el.className = 'li fup';
        const sc = {available:'s-av',in_use:'s-in',maintenance:'s-ma'}[v.status]||'s-av';
        const bc = {available:'bg-g',in_use:'bg-y',maintenance:'bg-r'}[v.status]||'bg-m';
        el.innerHTML = `
            <div class="lavt" style="background:var(--elevated);font-size:22px">🚚</div>
            <div class="lbody">
                <div class="ltitle">${esc(v.plate)} <span style="font-size:10px;color:var(--text-3)">${esc(VEH_TYPE[v.type]||v.type)}</span></div>
                <div class="lsub"><span class="sdot ${sc}"></span>${esc(STATUS_L[v.status]||v.status)}${v.driver_name?' · '+esc(v.driver_name):''} · ${Math.round(v.capacity_kg/19)} damacana</div>
            </div>
            <span class="badge ${bc}">${esc(STATUS_L[v.status]||v.status)}</span>
        `;
        container.appendChild(el);
    });
}

async function loadDashboard() {
    await Promise.all([loadStats(), loadCustomers(), loadOrders(), loadVehicles()]);
}

/* ══════════════════════════════════════════════════════════
   BOTTOM SHEET TAB RENDERERS
══════════════════════════════════════════════════════════ */
function renderInfoSheet(body) {
    const stats = [
        {label:'Toplam Abone', val: document.getElementById('kA').textContent, color:'var(--purple)'},
        {label:'Bekleyen Sipariş', val: document.getElementById('kS').textContent, color:'var(--amber)'},
        {label:'Müsait Araç', val: document.getElementById('kV').textContent, color:'var(--green)'},
        {label:'Bekleyen Damacana', val: document.getElementById('kD').textContent, color:'var(--accent)'},
    ];
    body.innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">
            ${stats.map(s=>`<div style="background:var(--elevated);border:1px solid var(--border-soft);border-radius:var(--r);padding:12px;text-align:center">
                <div style="font-size:28px;font-weight:900;color:${s.color}">${esc(s.val)}</div>
                <div style="font-size:11px;color:var(--text-3);margin-top:2px">${esc(s.label)}</div>
            </div>`).join('')}
        </div>
        <div class="sh"><span class="sh-title">Aboneler</span></div>
        <div id="bsCustList"></div>
        <div class="sh" style="margin-top:8px"><span class="sh-title">Siparişler</span></div>
        <div id="bsOrderList"></div>
    `;
    renderCustomerList(document.getElementById('bsCustList'), _custData);
    renderOrderList(document.getElementById('bsOrderList'), _orderData);
}

function renderRoutesSheet(body) {
    const rpc = document.getElementById('rpc').innerHTML;
    body.innerHTML = `<div id="bsRoutes">${rpc}</div>`;
}

function renderAddSheet(body) {
    body.innerHTML = `
        <div class="sh"><span class="sh-title">Yeni Su Abonesi</span></div>
        <label class="flabel">Ad Soyad *</label>
        <input type="text" id="bcName" class="finput" placeholder="Ahmet Yılmaz">
        <label class="flabel">Adres *</label>
        <input type="text" id="bcAddr" class="finput" placeholder="Atatürk Cad. No:5, Bucak">
        <div class="frow">
            <div><label class="flabel">Enlem</label><input type="number" step="any" id="bcLat" class="finput" placeholder="37.4558"></div>
            <div><label class="flabel">Boylam</label><input type="number" step="any" id="bcLng" class="finput" placeholder="30.5877"></div>
        </div>
        <div class="fhint" style="margin-bottom:8px">📍 Haritaya tıkla → koordinat dolar</div>
        <button class="btn btn-p btn-full" onclick="saveMobileCust()">Aboneyi Kaydet</button>
        <hr class="div" style="margin:12px 0">
        <div class="sh"><span class="sh-title">Yeni Araç</span></div>
        <label class="flabel">Plaka *</label>
        <input type="text" id="bvPlate" class="finput" placeholder="15 AB 123">
        <label class="flabel">Şoför Adı</label>
        <input type="text" id="bvDriver" class="finput" placeholder="Mehmet Kaya">
        <div class="frow">
            <div><label class="flabel">Kapasite (Damacana)</label><input type="number" id="bvCap" class="finput" placeholder="50"></div>
            <div><label class="flabel">Tip</label>
                <select id="bvType" class="fselect"><option value="van">Van</option><option value="truck">Kamyon</option><option value="motorcycle">Motorsiklet</option></select>
            </div>
        </div>
        <button class="btn btn-p btn-full" onclick="saveMobileVeh()">Aracı Kaydet</button>
    `;
    // Sync map click to mobile form
    if (map) {
        map.on('click', e => {
            const bl = document.getElementById('bcLat');
            const bn = document.getElementById('bcLng');
            if (bl) { bl.value = e.latlng.lat.toFixed(6); bn.value = e.latlng.lng.toFixed(6); }
        });
    }
}

async function saveMobileCust() {
    const name = (document.getElementById('bcName') ? document.getElementById('bcName').value.trim() : '');
    const address = (document.getElementById('bcAddr') ? document.getElementById('bcAddr').value.trim() : '');
    const lat = parseFloat(document.getElementById('bcLat') ? document.getElementById('bcLat').value : 0);
    const lng = parseFloat(document.getElementById('bcLng') ? document.getElementById('bcLng').value : 0);
    if (!name||!address||isNaN(lat)||isNaN(lng)) { toast('Tüm alanları doldurun.', false); return; }
    try {
        const r = await authFetch(`${BASE}/customers`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,address,lat,lng})});
        if (!r.ok) { const e=await r.json().catch(()=>({detail:'Hata'})); toast('Hata: '+(e.detail||r.statusText),false); return; }
        toast('Abone eklendi! 🎉'); loadDashboard(); switchBTab('info');
    } catch(e) { toast('Bağlantı hatası',false); }
}
async function saveMobileVeh() {
    const plate=(document.getElementById('bvPlate') ? document.getElementById('bvPlate').value.trim() : '');
    const cap=(document.getElementById('bvCap') ? document.getElementById('bvCap').value : '');
    const type=(document.getElementById('bvType') ? document.getElementById('bvType').value : '');
    const driver=(document.getElementById('bvDriver') ? document.getElementById('bvDriver').value.trim() : '')||null;
    if (!plate||!cap) { toast('Plaka ve kapasite zorunlu.',false); return; }
    try {
        const r=await authFetch(`${BASE}/vehicles`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plate,capacity_kg:parseFloat(cap)*19,type,status:'available',volume_m3:parseFloat(cap)*0.025})});
        if (!r.ok) { const e=await r.json().catch(()=>({detail:'Hata'})); toast('Hata: '+(e.detail||r.statusText),false); return; }
        toast('Araç eklendi! 🚚'); loadDashboard(); switchBTab('info');
    } catch(e) { toast('Bağlantı hatası',false); }
}

/* ══════════════════════════════════════════════════════════
   SAVE FORMS (Desktop)
══════════════════════════════════════════════════════════ */
async function saveCustomer() {
    const name=document.getElementById('cName').value.trim();
    const address=document.getElementById('cAddr').value.trim();
    const lat=parseFloat(document.getElementById('cLat').value);
    const lng=parseFloat(document.getElementById('cLng').value);
    if (!name||!address||isNaN(lat)||isNaN(lng)) { toast('Tüm alanları doldurun.', false); return; }
    try {
        const r=await authFetch(`${BASE}/customers`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,address,lat,lng})});
        if (!r.ok) { const e=await r.json().catch(()=>({detail:'Hata'})); toast('Hata: '+(e.detail||r.statusText),false); return; }
        ['cName','cAddr','cLat','cLng'].forEach(id => document.getElementById(id).value='');
        toast('Abone eklendi! 🎉'); loadDashboard();
    } catch(e) { toast('Bağlantı hatası',false); }
}
async function saveVehicle() {
    const plate=document.getElementById('vPlate').value.trim();
    const cap=document.getElementById('vCap').value;
    const type=document.getElementById('vType').value;
    const status=document.getElementById('vStatus').value;
    if (!plate||!cap) { toast('Plaka ve kapasite zorunlu.',false); return; }
    try {
        const r=await authFetch(`${BASE}/vehicles`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plate,capacity_kg:parseFloat(cap)*19,type,status,volume_m3:parseFloat(cap)*0.025})});
        if (!r.ok) { const e=await r.json().catch(()=>({detail:'Hata'})); toast('Hata: '+(e.detail||r.statusText),false); return; }
        ['vPlate','vDriver','vCap'].forEach(id => document.getElementById(id).value='');
        toast('Araç eklendi! 🚚'); loadDashboard();
    } catch(e) { toast('Bağlantı hatası',false); }
}

/* ══════════════════════════════════════════════════════════
   ROUTE RENDERING
══════════════════════════════════════════════════════════ */
function clearRoutes() { routeLayers.forEach(l=>map.removeLayer(l)); routeLayers=[]; }

function buildRouteCard(route, idx) {
    const color = COLORS[idx % COLORS.length];
    const sorted = [...route.stops].filter(s=>s.delivery_lat!=null&&s.delivery_lng!=null).sort((a,b)=>a.stop_sequence-b.stop_sequence);
    const totalBottles = route.stops.reduce((s,x)=>s+(x.bottle_count||0),0);

    const card = document.createElement('div');
    card.className = 'rcard fup';
    card.innerHTML = `
        <div class="rcard-head" onclick="this.parentElement.classList.toggle('open')">
            <div class="rcol" style="background:${color}"></div>
            <div class="rctitle">${esc(route.name||'Araç #'+route.vehicle_id)}</div>
            <span class="badge bg-a">${esc(String(route.stops.length))}</span>
            <span class="rcchev">▼</span>
        </div>
        <div class="rmetag">
            <div class="rmitem"><div class="rmlabel">Mesafe</div><div class="rmval">${route.total_distance_km!=null?esc(route.total_distance_km.toFixed(1))+' km':'—'}</div></div>
            <div class="rmitem"><div class="rmlabel">Süre</div><div class="rmval">${route.total_duration_min!=null?esc(String(route.total_duration_min))+' dk':'—'}</div></div>
            <div class="rmitem"><div class="rmlabel">Damacana</div><div class="rmval">${esc(String(totalBottles))} adet</div></div>
            <div class="rmitem"><div class="rmlabel">Durum</div><div class="rmval" style="color:var(--green);font-size:11px">✓ Hazır</div></div>
        </div>
        <div class="rstops">
            ${sorted.map((s,i)=>`
                <div class="stopitem">
                    <div class="stopnum" style="color:${color}">${i+1}</div>
                    <div class="stopbody">
                        <div class="stoptitle">${s.bottle_count!=null?esc(String(s.bottle_count))+' dolu, '+esc(String(s.empty_returns_expected||0))+' iade':'Sipariş #'+esc(String(s.order_id))}</div>
                        <div class="stopsub">${esc((s.weight_kg||0).toFixed(1))} kg</div>
                    </div>
                    <button class="navbtn" onclick="nav(${s.delivery_lat},${s.delivery_lng})">📍</button>
                </div>
            `).join('')}
        </div>
    `;
    return { card, sorted, color };
}

function renderRoutes(data) {
    clearRoutes();
    const rpc = document.getElementById('rpc');
    rpc.innerHTML = '';

    if (!(data.routes && data.routes.length)) {
        rpc.innerHTML = `<div class="empty"><div class="ei">🤔</div><div class="et">Rota oluşturulamadı</div></div>`;
        return;
    }

    const s = data.summary;
    document.getElementById('rpSub').textContent = `${s.total_vehicles_used} araç · ${s.total_orders_assigned} sipariş · ${s.total_distance_km.toFixed(1)} km`;

    const allCoords = [];

    data.routes.forEach((route, idx) => {
        const { card, sorted, color } = buildRouteCard(route, idx);
        rpc.appendChild(card);

        const coords = sorted.map(s=>[s.delivery_lat,s.delivery_lng]);
        if (coords.length < 2) return;
        allCoords.push(...coords);

        if (map) {
            let pCoords = coords;
            if (route.route_geometry) {
                try {
                    const g = JSON.parse(route.route_geometry);
                    const m = (g.coordinates||[]).map(c=>[c[1],c[0]]);
                    if (m.length >= 2) pCoords = m;
                } catch(_) {}
            }
            const poly = L.polyline(pCoords, {color, weight:4, opacity:.85}).addTo(map);
            routeLayers.push(poly);

            sorted.forEach((stop,i) => {
                const mk = L.marker(coords[i], {icon:stopIcon(i+1,color)}).addTo(map);
                mk.bindPopup(popupHtml(`Durak ${i+1}`, route.name||`Rota ${idx+1}`,
                    [['Dolu Damacana',(stop.bottle_count||0)+' adet'],['Boş İade',(stop.empty_returns_expected||0)+' adet'],['Ağırlık',(stop.weight_kg||0).toFixed(1)+' kg']],
                    coords[i][0], coords[i][1]
                ));
                routeLayers.push(mk);
            });
        }
    });

    if (allCoords.length && map) map.fitBounds(L.latLngBounds(allCoords),{padding:[40,40]});

    // If routes panel is hidden, show it
    const rp = document.getElementById('rpanel');
    if (rp && rp.classList.contains('hidden')) toggleRoutes();
}

/* ══════════════════════════════════════════════════════════
   OPTIMIZATION
══════════════════════════════════════════════════════════ */
async function runOptimization() {
    const btn = document.getElementById('hbOpt');
    const mBtn = document.getElementById('mbOpt');
    if (btn) { btn.disabled=true; btn.textContent='⏳ Hesaplanıyor...'; }
    if (mBtn) { mBtn.disabled=true; }
    loading(true, 'Rota optimizasyonu çalışıyor...');

    let url = `${BASE}/optimize/run`;
    if ('geolocation' in navigator) {
        try {
            const pos = await new Promise((res,rej) => navigator.geolocation.getCurrentPosition(res,rej,{enableHighAccuracy:true,timeout:8000,maximumAge:60000}));
            url += `?origin_lat=${pos.coords.latitude.toFixed(6)}&origin_lng=${pos.coords.longitude.toFixed(6)}`;
        } catch(_) {}
    }

    try {
        const r = await authFetch(url, {method:'POST'});
        if (!r.ok) { const e=await r.json().catch(()=>({detail:'Sunucu hatası'})); toast('Hata: '+(e.detail||r.statusText),false); return; }
        const d = await r.json();
        renderRoutes(d);
        toast(`✅ ${d.summary.total_orders_assigned} sipariş ${d.summary.total_vehicles_used} araca atandı`);
        loadDashboard();
    } catch(e) { toast('Bağlantı hatası: '+e.message, false); }
    finally {
        if (btn) { btn.disabled=false; btn.innerHTML='⚡ Optimize Et'; }
        if (mBtn) { mBtn.disabled=false; }
        loading(false);
    }
}

/* ══════════════════════════════════════════════════════════
   DRIVER MODE
══════════════════════════════════════════════════════════ */
async function enterDriverMode() {
    loading(true, 'Rotalar yükleniyor...');
    let vehicles = [];
    try {
        const r = await authFetch(`${BASE}/delivery/today-routes`);
        if (r.ok) vehicles = await r.json();
    } catch(_) {}
    finally { loading(false); }

    document.getElementById('driverMode').classList.add('on');

    if (vehicles.length === 0) {
        renderVehiclePicker([]);
    } else if (vehicles.length === 1) {
        // Tek araç — dogrudan rotaya git
        await loadRouteForVehicle(vehicles[0].vehicle_id);
    } else {
        // Çoklu araç — seçim ekrani
        renderVehiclePicker(vehicles);
    }
}

function renderVehiclePicker(vehicles) {
    const wrap = document.getElementById('dmCardWrap');
    document.getElementById('dmProg').textContent = 'Araç Seç';
    document.getElementById('dmProgBar').style.width = '0%';

    if (!vehicles.length) {
        wrap.innerHTML = `
            <div class="vp-no-route">
                <div class="vp-no-icon">🚧</div>
                <div class="vp-no-title">Bugün için rota yok</div>
                <div class="vp-no-sub">Yönetici ekranından "Dağıtımı Optimize Et" butonuna basılması gerekiyor.</div>
                <button class="btn btn-outline" style="margin-top:8px" onclick="exitDriverMode()">← Geri Dön</button>
            </div>
        `;
        return;
    }

    const vTypeIcon = { van:'🚐', truck:'🚛', motorcycle:'🏍', bicycle:'🚲' };
    wrap.innerHTML = `
        <div class="vp-screen">
            <div class="vp-title">Hangi araç senin?</div>
            <div class="vp-sub">Plakana dokunarak rotanı aç</div>
            ${vehicles.map(v => `
                <div class="vp-card fup" onclick="loadRouteForVehicle(${esc(String(v.vehicle_id))})" role="button" tabindex="0">
                    <div class="vp-truck">${vTypeIcon[v.vehicle_type] || '🚚'}</div>
                    <div class="vp-body">
                        <div class="vp-plate">${esc(v.plate)}</div>
                        <div class="vp-detail">${v.driver_name ? esc(v.driver_name) + ' · ' : ''}${esc(String(v.completed_stops))}/${esc(String(v.total_stops))} tamamlandı</div>
                    </div>
                    <div class="vp-stops">
                        <div class="vp-stops-num">${esc(String(v.total_stops - v.completed_stops))}</div>
                        <div class="vp-stops-label">KALAN</div>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

async function loadRouteForVehicle(vehicleId) {
    loading(true, 'Rota yükleniyor...');
    try {
        const r = await authFetch(`${BASE}/delivery/today-route?vehicle_id=${vehicleId}`);
        if (!r.ok) {
            const e = await r.json().catch(() => ({detail:'Rota bulunamadı'}));
            toast('Hata: '+(e.detail||r.statusText), false);
            return;
        }
        dmRoute = await r.json();
        dmStopIdx = dmRoute.stops.findIndex(s => s.status !== 'completed');
        if (dmStopIdx < 0) dmStopIdx = dmRoute.stops.length;
        dmReturns = 0;
        const title = document.querySelector('.dm-htitle');
        if (title && dmRoute.plate) title.textContent = '🚚 ' + dmRoute.plate;
    } catch(e) { toast('Bağlantı hatası: '+e.message, false); return; }
    finally { loading(false); }

    renderDriverStop();
}

function exitDriverMode() {
    document.getElementById('driverMode').classList.remove('on');
    dmRoute = null; dmStopIdx = 0; dmReturns = 0;
}

function renderDriverStop() {
    const wrap = document.getElementById('dmCardWrap');

    if (!dmRoute || dmStopIdx >= dmRoute.stops.length) {
        // All done!
        wrap.innerHTML = `
            <div class="dm-done-screen">
                <div class="dm-done-icon">🎉</div>
                <div class="dm-done-title">Tüm Teslimatlar Tamamlandı!</div>
                <div class="dm-done-sub">Bugünkü ${esc(String((dmRoute ? dmRoute.total_stops : 0)))} abonenin teslimatı başarıyla gerçekleştirildi.<br>Harika iş çıkardınız!</div>
                <button class="btn btn-p" style="margin-top:16px;min-height:56px;width:100%;max-width:300px;font-size:16px" onclick="exitDriverMode()">Ana Ekrana Dön</button>
            </div>
        `;
        updateProgress((dmRoute ? dmRoute.total_stops : 0), (dmRoute ? dmRoute.total_stops : 0));
        return;
    }

    const stop = dmRoute.stops[dmStopIdx];
    const completedCount = dmRoute.stops.filter(s=>s.status==='completed').length;
    updateProgress(completedCount, dmRoute.total_stops);

    dmReturns = stop.empty_returns_expected; // default to expected

    const card = document.createElement('div');
    card.className = 'dm-card slide-in';
    card.innerHTML = `
        <div class="dm-stop-num">
            <div class="dm-stop-badge">${esc(String(stop.stop_sequence))}</div>
            DURAK ${esc(String(stop.stop_sequence))} / ${esc(String(dmRoute.total_stops))}
        </div>

        <div class="dm-customer">${esc(stop.customer_name || 'Müşteri #'+stop.order_id)}</div>
        <div class="dm-address">📍 <span>${esc(stop.delivery_address)}</span></div>

        <div class="dm-bottles">
            <div class="dm-bottle-card full">
                <div class="dm-bottle-ico">💧</div>
                <div class="dm-bottle-num">${esc(String(stop.bottle_count))}</div>
                <div class="dm-bottle-label">DOLU VER</div>
            </div>
            <div class="dm-bottle-card ret">
                <div class="dm-bottle-ico">♻️</div>
                <div class="dm-bottle-num" id="dmExpRet">${esc(String(stop.empty_returns_expected))}</div>
                <div class="dm-bottle-label">BOŞ BEKLENEN</div>
            </div>
        </div>

        <!-- Gerçek boş iade sayacı -->
        <div class="dm-return-row">
            <div>
                <div class="dm-return-label">Gerçekte Kaç Boş Alındı?</div>
                <div class="lsub" style="color:var(--text-3);font-size:11px;margin-top:2px">Beklenen: ${esc(String(stop.empty_returns_expected))}</div>
            </div>
            <div class="dm-counter">
                <button class="dm-counter-btn" onclick="changeReturns(-1)" id="dmRetMinus">−</button>
                <div class="dm-counter-val" id="dmRetVal">${esc(String(stop.empty_returns_expected))}</div>
                <button class="dm-counter-btn" onclick="changeReturns(1)">+</button>
            </div>
        </div>

        <div class="dm-actions">
            <button class="dm-nav-btn" onclick="nav(${stop.delivery_lat},${stop.delivery_lng})">
                📍 Navigasyonu Başlat
            </button>
            <button class="dm-done-btn" id="dmDoneBtn" onclick="completeStop()">
                ✅ Teslim Edildi
            </button>
            <button class="dm-skip-btn" onclick="skipStop()">Bu durağı atla →</button>
        </div>
    `;

    wrap.innerHTML = '';
    wrap.appendChild(card);
}

function updateProgress(done, total) {
    const pct = total > 0 ? (done / total * 100) : 0;
    document.getElementById('dmProg').textContent = `${done}/${total}`;
    document.getElementById('dmProgBar').style.width = pct + '%';
}

function changeReturns(delta) {
    dmReturns = Math.max(0, dmReturns + delta);
    const el = document.getElementById('dmRetVal');
    if (el) el.textContent = dmReturns;
    const minus = document.getElementById('dmRetMinus');
    if (minus) minus.disabled = dmReturns === 0;
}

async function completeStop() {
    const stop = (dmRoute ? dmRoute.stops[dmStopIdx] : null);
    if (!stop) return;

    const btn = document.getElementById('dmDoneBtn');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Kaydediliyor...'; }

    try {
        const r = await authFetch(`${BASE}/delivery/routes/${dmRoute.route_id}/stops/${stop.stop_sequence}/complete`, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ empty_returns_actual: dmReturns })
        });
        if (!r.ok) {
            const e = await r.json().catch(()=>({detail:'Kayıt hatası'}));
            toast('Hata: '+(e.detail||r.statusText), false);
            if (btn) { btn.disabled=false; btn.textContent='✅ Teslim Edildi'; }
            return;
        }
        const result = await r.json();

        // Update local state
        dmRoute.stops[dmStopIdx].status = 'completed';
        dmRoute.completed_stops = result.completed_stops;

        if (result.route_complete) {
            dmStopIdx = dmRoute.stops.length; // trigger done screen
        } else {
            // Animate out and find next uncompleted stop
            const card = document.querySelector('.dm-card');
            if (card) card.classList.add('slide-out');
            await new Promise(res => setTimeout(res, 260));
            dmStopIdx = dmRoute.stops.findIndex((s,i) => i > dmStopIdx && s.status !== 'completed');
            if (dmStopIdx < 0) dmStopIdx = dmRoute.stops.length;
            dmReturns = 0;
        }

        loadDashboard(); // Refresh KPIs
        renderDriverStop();
    } catch(e) {
        toast('Bağlantı hatası: '+e.message, false);
        if (btn) { btn.disabled=false; btn.textContent='✅ Teslim Edildi'; }
    }
}

async function skipStop() {
    if (!confirm('Bu durağı atlamak istediğinizden emin misiniz?')) return;
    const stop = (dmRoute ? dmRoute.stops[dmStopIdx] : null);
    if (!stop) return;
    // Mark as skipped locally
    dmRoute.stops[dmStopIdx].status = 'skipped';
    dmStopIdx = dmRoute.stops.findIndex((s,i) => i > dmStopIdx && s.status === 'pending');
    if (dmStopIdx < 0) dmStopIdx = dmRoute.stops.length;
    dmReturns = 0;
    renderDriverStop();
}

/* ══════════════════════════════════════════════════════════
   PWA — Service Worker & Install
══════════════════════════════════════════════════════════ */
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/static/sw.js')
            .then(reg => console.log('[SW] Registered', reg.scope))
            .catch(err => console.warn('[SW] Registration failed', err));
    });
}

let deferredPrompt = null;
window.addEventListener('beforeinstallprompt', e => {
    e.preventDefault();
    deferredPrompt = e;
    document.getElementById('installBanner').classList.add('show');
});
document.getElementById('ibInstall').addEventListener('click', async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    deferredPrompt = null;
    document.getElementById('installBanner').classList.remove('show');
    if (outcome === 'accepted') toast('Uygulama yüklendi! 🎉');
});
window.addEventListener('appinstalled', () => {
    document.getElementById('installBanner').classList.remove('show');
    toast('Uygulama başarıyla yüklendi!');
});

/* ══════════════════════════════════════════════════════════
   BOOT
══════════════════════════════════════════════════════════ */

if (document.readyState === 'loading') {
    // DOM hala yükleniyor, event'i dinle
    document.addEventListener('DOMContentLoaded', () => {
        initMap();
        setTimeout(() => map.invalidateSize(), 350);
        loadDashboard();
        
        // Check if started in driver mode (PWA shortcut)
        if (location.hash === '#driver') {
            setTimeout(enterDriverMode, 800);
        }
    });
} else {
    // DOM zaten yüklendi
    initMap();
    setTimeout(() => map.invalidateSize(), 350);
    loadDashboard();
    
    // Check if started in driver mode (PWA shortcut)
    if (location.hash === '#driver') {
        setTimeout(enterDriverMode, 800);
    }
}