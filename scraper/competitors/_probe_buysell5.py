"""cities API + store_area taxonomy + geolocation field"""
import sys, io, json, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

H = {"User-Agent": "Mozilla/5.0 Windows Chrome/124", "Accept-Language": "ja"}

# 1) cities API with pref params
print("=== cities API ===")
for pref in ["東京都","神奈川県","埼玉県","千葉県","13","14","11","12","tokyo","kanagawa"]:
    r = requests.post("https://buysell-kaitori.com/wp-json/bsportal/v1/cities",
                      headers=H, json={"pref": pref}, timeout=10)
    try:
        d = r.json()
        if d.get("success"):
            print(f"  pref={pref!r}: SUCCESS data={str(d.get('data',''))[:200]}")
        else:
            print(f"  pref={pref!r}: {d.get('data','')[:80]}")
    except:
        print(f"  pref={pref!r}: parse error")

# 2) store_post with geolocation field
print("\n=== store_post geolocation ===")
r2 = requests.get("https://buysell-kaitori.com/wp-json/wp/v2/store_post?per_page=5&_fields=id,title,geolocation,store_area,link", headers=H)
d2 = r2.json()
for s in d2[:5]:
    print(f"  {s.get('title',{}).get('rendered','')[:35]}")
    print(f"    geolocation: {s.get('geolocation','')}")
    print(f"    store_area: {s.get('store_area','')}")
    print(f"    link: {s.get('link','')[-50:]}")

# 3) store_area taxonomy
print("\n=== store_area terms ===")
r3 = requests.get("https://buysell-kaitori.com/wp-json/wp/v2/store_area?per_page=100", headers=H)
areas = r3.json()
print(f"total areas: {len(areas)}")
for a in areas[:15]:
    print(f"  id={a.get('id')} name={a.get('name')} slug={a.get('slug')} count={a.get('count',0)}")

# 4) store_post with store_area filter
print("\n=== store_post by store_area ===")
# まず東京のエリアIDを特定
tokyo_areas = [a for a in areas if '東京' in a.get('name','') or 'tokyo' in a.get('slug','')]
print(f"東京関連 areas: {[(a['id'],a['name']) for a in tokyo_areas[:5]]}")

if tokyo_areas:
    area_id = tokyo_areas[0]['id']
    r4 = requests.get(f"https://buysell-kaitori.com/wp-json/wp/v2/store_post?per_page=100&store_area={area_id}&_fields=id,title,geolocation,link", headers=H)
    d4 = r4.json()
    print(f"area_id={area_id} → {len(d4)}件 (total={r4.headers.get('X-WP-Total','?')})")
    for s in d4[:3]:
        print(f"  {s.get('title',{}).get('rendered','')[:40]} geo={s.get('geolocation','')}")

# 5) addl-sitemap.xml に store_post URLs?
print("\n=== addl-sitemap.xml ===")
r5 = requests.get("https://buysell-kaitori.com/addl-sitemap.xml", headers=H, timeout=15)
print(f"status: {r5.status_code} size: {len(r5.text)}")
print(r5.text[:1000])
