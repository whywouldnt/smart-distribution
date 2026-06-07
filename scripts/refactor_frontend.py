import os
import re

html_path = 'static/index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    content = f.read()

# CSS ayiklama
style_match = re.search(r'<style>(.*?)</style>', content, re.DOTALL)
if style_match:
    style_content = style_match.group(1).strip()
    os.makedirs('static/css', exist_ok=True)
    with open('static/css/style.css', 'w', encoding='utf-8') as f:
        f.write(style_content)
    content = content.replace(style_match.group(0), '<link rel="stylesheet" href="/static/css/style.css">')

# JS ayiklama
script_matches = re.findall(r'<script>(.*?)</script>', content, re.DOTALL)
for s in script_matches:
    if len(s) > 100:
        os.makedirs('static/js', exist_ok=True)
        with open('static/js/app.js', 'w', encoding='utf-8') as f:
            f.write(s.strip())
        content = content.replace('<script>' + s + '</script>', '<script src="/static/js/app.js"></script>')

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Frontend refactoring successful!')
