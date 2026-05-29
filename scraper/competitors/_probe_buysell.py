import sys, io, json, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
H = {"User-Agent": "Mozilla/5.0 Windows Chrome/124", "Accept-Language": "ja"}

# パラメータ試行
for params in ["", "?limit=1000", "?per_page=1000", "?all=1", "?pref=13", "?page=2"]:
    url = f"https://buysell-kaitori.com/wp-json/bsportal/v1/stores{params}"
    r = requests.get(url, headers=H, timeout=15)
    try:
        data = r.json()
        cnt = len(data.get("data",{}).get("list",[])) if isinstance(data,dict) else len(data)
    except:
        cnt = "parse_err"
    print(f"params={params!r:20s} status={r.status_code} list_len={cnt}")

# store_post WP REST API
print()
r2 = requests.get("https://buysell-kaitori.com/wp-json/wp/v2/store_post?per_page=100&page=1&_fields=id,title,acf,meta,link", headers=H)
d2 = r2.json()
total = r2.headers.get("X-WP-Total","?")
pages = r2.headers.get("X-WP-TotalPages","?")
print(f"store_post: total={total} pages={pages} returned={len(d2)}")
if d2:
    print("  keys:", list(d2[0].keys()))
    print("  acf:", json.dumps(d2[0].get("acf",""), ensure_ascii=False)[:200])
    print("  title:", d2[0].get("title",{}).get("rendered","")[:50])
    print("  link:", d2[0].get("link","")[:60])

# store_post ページ1の全件でアドレス確認
print()
for s in d2[:3]:
    print(f"  {s.get('title',{}).get('rendered','')[:40]} | acf={json.dumps(s.get('acf',''), ensure_ascii=False)[:100]}")
