"""最終確認: バイセル /bsportal/v1/stores + おたからや area=379"""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 Windows Chrome/124", "Accept-Language": "ja,en;q=0.9"}
def get(url, **kw):
    r = requests.get(url, headers=HEADERS, timeout=30, **kw)
    return r

# =============================================
# 1) バイセル /bsportal/v1/stores
# =============================================
print("=== バイセル /bsportal/v1/stores ===")
r = get("https://buysell-kaitori.com/wp-json/bsportal/v1/stores")
print(f"status: {r.status_code}, size: {len(r.text)}")
if r.status_code == 200:
    try:
        data = r.json()
        print(f"type: {type(data)}")
        if isinstance(data, list):
            print(f"count: {len(data)}")
            s = data[0]
            print(f"keys: {list(s.keys())}")
            print(f"sample: {json.dumps(s, ensure_ascii=False)[:400]}")
        elif isinstance(data, dict):
            print(f"keys: {list(data.keys())}")
            print(str(data)[:400])
    except Exception as e:
        print(f"JSON parse error: {e}")
        print(r.text[:500])

# store_post WP type も試す
print("\n--- store_post WP type ---")
r2 = get("https://buysell-kaitori.com/wp-json/wp/v2/store_post?per_page=3&_fields=id,title,acf,meta,link")
print(f"status: {r2.status_code}")
if r2.status_code == 200:
    d2 = r2.json()
    print(f"count: {len(d2)}, total: {r2.headers.get('X-WP-Total','?')}")
    if d2:
        print(f"keys: {list(d2[0].keys())}")
        print(f"sample: {json.dumps(d2[0], ensure_ascii=False)[:500]}")

# store_area taxonomy
print("\n--- store_area taxonomy ---")
r3 = get("https://buysell-kaitori.com/wp-json/wp/v2/store_area?per_page=50")
if r3.status_code == 200:
    areas3 = r3.json()
    print(f"areas count: {len(areas3)}")
    for a in areas3[:10]:
        print(f"  id={a.get('id')} name={a.get('name')} slug={a.get('slug')}")

# =============================================
# 2) おたからや - 東京(id=379)でフィルタ確認
# =============================================
print("\n=== おたからや area=379 (東京都) ===")
r4 = get("https://www.otakaraya.jp/wp-json/wp/v2/shop?per_page=5&area=379&_fields=id,title,acf,link")
print(f"status: {r4.status_code}, total: {r4.headers.get('X-WP-Total','?')}, pages: {r4.headers.get('X-WP-TotalPages','?')}")
if r4.status_code == 200:
    for s in r4.json():
        link = s.get('link','')
        acf = s.get('acf',{})
        mp = acf.get('map_position',{})
        # 住所フィールドも確認
        addr = acf.get('shop_address','') or acf.get('address','')
        print(f"  title: {s['title']['rendered'][:40]}")
        print(f"  link: {link}")
        print(f"  lat={mp.get('lat','')} lng={mp.get('lng','')}")
        print(f"  acf keys: {list(acf.keys())}")
        print()

# 1都3県のterm IDを確認
print("=== おたからや area taxonomy IDs for 1都3県 ===")
for slug, name in [("tokyo","東京都"), ("kanagawa","神奈川"), ("saitama","埼玉"), ("chiba","千葉")]:
    r5 = get(f"https://www.otakaraya.jp/wp-json/wp/v2/area?search={name[:3]}&per_page=5")
    if r5.status_code == 200:
        for a in r5.json():
            if any(k in a.get('name','') for k in [name[:3], slug]):
                print(f"  {name}: id={a.get('id')} slug={a.get('slug')}")
