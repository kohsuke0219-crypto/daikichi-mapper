"""バイセルの全店舗取得方法を探る"""
import sys, io, json, requests, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

H = {"User-Agent": "Mozilla/5.0 Windows Chrome/124", "Accept-Language": "ja",
     "Accept": "application/json, text/plain, */*"}

def get_json(url):
    r = requests.get(url, headers=H, timeout=15)
    try:
        return r.status_code, r.json(), r.headers
    except:
        return r.status_code, None, r.headers

# 1) pref_index パラメータ
print("=== pref_index param ===")
for pi in range(5):
    status, data, hdrs = get_json(f"https://buysell-kaitori.com/wp-json/bsportal/v1/stores?pref_index={pi}")
    cnt = len(data.get("data",{}).get("list",[])) if data else 0
    if cnt > 0:
        first = data["data"]["list"][0]
        print(f"  pref_index={pi}: {cnt}件 code_value={first.get('code_value','')} name={first.get('store_post_name','')[:30]}")
    else:
        print(f"  pref_index={pi}: {cnt}件")

# 2) store_post WP: content に住所が入っているページを確認
print("\n=== store_post content詳細 ===")
# protected=false を試す
r2 = requests.get("https://buysell-kaitori.com/wp-json/wp/v2/store_post?per_page=3&status=publish&_fields=id,title,link,content,rendered", headers=H)
d2 = r2.json()
for s in d2[:2]:
    print(f"  {s.get('title',{}).get('rendered','')[:40]} content={str(s.get('content',''))[:200]}")

# 3) 検索ページのHTMLから データを取得
print("\n=== 店舗一覧ページ script 内 JSON ===")
r3 = requests.get("https://buysell-kaitori.com/shop/list/", headers=H, timeout=20)
# scriptタグ内のJSONを探す
scripts = re.findall(r'<script[^>]*>(.*?)</script>', r3.text, re.DOTALL)
for sc in scripts:
    if "store" in sc.lower() and ("lat" in sc or "address" in sc or "zip" in sc):
        print(f"  script with store data: {sc[:500]}")
        break

# wp-json の bsportal namespace を確認
print("\n=== bsportal namespace ===")
r4 = requests.get("https://buysell-kaitori.com/wp-json/bsportal/v1", headers=H)
print(f"status: {r4.status_code}")
if r4.status_code == 200:
    print(str(r4.text)[:1000])

# 4) 店舗マップページ → JavaScript 変数に全店舗データがあるか
print("\n=== 店舗一覧API試行 ===")
for ep in [
    "https://buysell-kaitori.com/wp-json/bsportal/v1/stores/all",
    "https://buysell-kaitori.com/wp-json/bsportal/v1/all-stores",
    "https://buysell-kaitori.com/wp-json/bsportal/v1/stores?pref=tokyo",
    "https://buysell-kaitori.com/wp-json/bsportal/v1/stores?code_value=13",
    "https://buysell-kaitori.com/wp-json/bsportal/v1/stores?pref_code=13",
]:
    status, data, _ = get_json(ep)
    cnt = len(data.get("data",{}).get("list",[])) if data else 0
    print(f"  {ep[-60:]}: status={status} cnt={cnt}")
