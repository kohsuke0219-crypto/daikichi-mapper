"""バイセル cities API + POST方式 + sitemap探索"""
import sys, io, json, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

H = {"User-Agent": "Mozilla/5.0 Windows Chrome/124", "Accept-Language": "ja"}

# 1) cities エンドポイント
print("=== /bsportal/v1/cities ===")
r = requests.get("https://buysell-kaitori.com/wp-json/bsportal/v1/cities", headers=H, timeout=15)
print(f"status: {r.status_code}, size: {len(r.text)}")
try:
    data = r.json()
    print(type(data), str(data)[:500])
except:
    print(r.text[:300])

# 2) POST に lat/lng
print("\n=== POST lat/lng ===")
for lat, lng, name in [
    (35.69, 139.69, "東京中央"),
    (35.45, 139.64, "横浜"),
    (35.85, 139.65, "さいたま"),
    (35.60, 140.12, "千葉"),
]:
    r2 = requests.post("https://buysell-kaitori.com/wp-json/bsportal/v1/stores",
                       headers={**H, "Content-Type": "application/json"},
                       json={"lat": lat, "lng": lng}, timeout=15)
    try:
        d2 = r2.json()
        lst = d2.get("data",{}).get("list",[])
        codes = [str(s.get("code_value",""))[:2] for s in lst]
        first_name = lst[0].get("store_post_name","") if lst else ""
        print(f"  [{name}] lat={lat} lng={lng}: {len(lst)}件 codes={set(codes)} first={first_name[:30]}")
    except:
        print(f"  [{name}]: parse error {r2.status_code} {r2.text[:100]}")

# 3) POST form-data
print("\n=== POST form-data ===")
r3 = requests.post("https://buysell-kaitori.com/wp-json/bsportal/v1/stores",
                   headers=H, data={"lat": "35.69", "lng": "139.69", "limit": "500"}, timeout=15)
try:
    d3 = r3.json()
    cnt = len(d3.get("data",{}).get("list",[]))
    print(f"form-data POST: {cnt}件")
except:
    print(f"form-data: {r3.status_code} {r3.text[:200]}")

# 4) sitemap
print("\n=== sitemap ===")
r4 = requests.get("https://buysell-kaitori.com/sitemap.xml", headers=H, timeout=15)
print(f"sitemap: {r4.status_code} size={len(r4.text)}")
print(r4.text[:800])

# 5) store_post に taxonomy filter
print("\n=== store_post + taxonomy ===")
r5 = requests.get("https://buysell-kaitori.com/wp-json/wp/v2/taxonomies", headers=H)
taxos = r5.json()
for name, info in taxos.items():
    if "store" in name or "area" in name or "pref" in name or "region" in name:
        print(f"  taxonomy: {name} → {info.get('rest_base','')}")

# store_post linked taxonomies
r6 = requests.get("https://buysell-kaitori.com/wp-json/wp/v2/store_post?per_page=1&_embed=1", headers=H)
d6 = r6.json()
if d6:
    print("\nstore_post _embed first item keys:", list(d6[0].keys()))
    embed = d6[0].get('_embedded', {})
    print("_embedded keys:", list(embed.keys()))
