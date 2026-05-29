"""バイセル API探索 + おたからや 都道府県フィルタ確認"""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 Windows Chrome/124", "Accept-Language": "ja,en;q=0.9"}
def get(url, **kw):
    r = requests.get(url, headers=HEADERS, timeout=30, **kw)
    return r

# =============================================
# 1) バイセル - エンドポイント候補を総当たり
# =============================================
print("=== バイセル REST API 探索 ===")
# まず公開されているタイプを確認
r = get("https://buysell-kaitori.com/wp-json/wp/v2/types")
if r.status_code == 200:
    types = r.json()
    for name, info in types.items():
        if isinstance(info, dict):
            print(f"  type: {name} → rest_base={info.get('rest_base','')}")

# カスタムポストタイプをいろいろ試す
for ep in ["shops","stores","spot","store_info","shopinfo","kaitori_shop","locations",
           "branch","office","shop_list","tenpo"]:
    r2 = get(f"https://buysell-kaitori.com/wp-json/wp/v2/{ep}?per_page=1")
    if r2.status_code == 200:
        print(f"  ✅ /wp-json/wp/v2/{ep}: OK, Total={r2.headers.get('X-WP-Total','?')}")
        d = r2.json()
        if d:
            print(f"     title: {d[0].get('title',{}).get('rendered','')[:50]}")
            print(f"     keys: {list(d[0].keys())[:12]}")
    elif r2.status_code != 404:
        print(f"  ? /wp-json/wp/v2/{ep}: {r2.status_code}")

# WP REST API のルート一覧
print("\n--- WP REST routes ---")
r3 = get("https://buysell-kaitori.com/wp-json/")
if r3.status_code == 200:
    routes = r3.json().get("routes", {})
    for route in routes:
        if any(k in route for k in ["shop","store","spot","kaitori","branch","tenpo","location"]):
            print(f"  route: {route}")

# =============================================
# 2) おたからや - 東京の店舗をAPIで取得
# =============================================
print("\n=== おたからや - area taxonomy で東京フィルタ ===")
# まず area taxonomy の term を確認
r4 = get("https://www.otakaraya.jp/wp-json/wp/v2/area?search=東京&per_page=5")
print(f"area taxonomy search=東京: {r4.status_code}")
if r4.status_code == 200:
    areas = r4.json()
    for a in areas[:5]:
        print(f"  id={a.get('id')} name={a.get('name')} slug={a.get('slug')}")

r5 = get("https://www.otakaraya.jp/wp-json/wp/v2/area?per_page=50")
print(f"area taxonomy all: {r5.status_code}")
if r5.status_code == 200:
    areas5 = r5.json()
    print(f"  total areas: {len(areas5)}")
    # 1都3県を探す
    for a in areas5:
        nm = a.get('name','')
        if any(k in nm for k in ['東京','東京都','tokyo','神奈川','埼玉','千葉']):
            print(f"  id={a.get('id')} name={nm} slug={a.get('slug')}")

# 東京の店舗をAPIで直接取得(area=13のようなIDフィルタを試す)
print("\n--- おたからや 東京 店舗サンプル ---")
r6 = get("https://www.otakaraya.jp/wp-json/wp/v2/shop?per_page=3&_fields=id,title,acf,link&area=13")
print(f"area=13: {r6.status_code}")
if r6.status_code == 200 and r6.json():
    for s in r6.json():
        acf = s.get('acf', {})
        mp = acf.get('map_position', {})
        print(f"  {s['title']['rendered'][:40]} lat={mp.get('lat','')} lng={mp.get('lng','')}")

# link ベースでの東京店舗確認
r7 = get("https://www.otakaraya.jp/wp-json/wp/v2/shop?per_page=5&_fields=id,title,acf,link")
if r7.status_code == 200:
    for s in r7.json():
        link = s.get('link','')
        acf = s.get('acf',{})
        mp = acf.get('map_position',{})
        print(f"  link={link[30:70]} lat={mp.get('lat','')} lng={mp.get('lng','')}")
