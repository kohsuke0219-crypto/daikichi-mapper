import sys, io, json, requests, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from bs4 import BeautifulSoup
H = {"User-Agent": "Mozilla/5.0 Windows Chrome/124", "Accept-Language": "ja"}

# store_post に content/meta があるか確認
r = requests.get("https://buysell-kaitori.com/wp-json/wp/v2/store_post?per_page=5&_fields=id,title,link,content,meta,excerpt", headers=H)
d = r.json()
for s in d[:2]:
    print(f"title: {s.get('title',{}).get('rendered','')[:40]}")
    print(f"link:  {s.get('link','')[:80]}")
    content = s.get('content',{}).get('rendered','') or ''
    print(f"content_len: {len(content)}")
    print(f"content[:500]: {content[:500]}")
    print(f"meta: {s.get('meta','')}")
    print()

# 個別店舗ページからアドレス取得を試す
print("=== 個別店舗ページ ===")
r2 = requests.get("https://buysell-kaitori.com/store_post/%e9%ab%98%e5%b0%be%e5%90%8d%e5%ba%97%e8%a1%97%e5%ba%97/", headers=H, timeout=20)
soup = BeautifulSoup(r2.text, "html.parser")

# JSON-LDを探す
for script in soup.find_all("script", type="application/ld+json"):
    txt = script.string or ''
    if txt:
        print("JSON-LD:", txt[:400])

# 住所候補
for pat in ["住所", "address", "〒", "東京"]:
    elems = [e for e in soup.find_all(True) if pat in (e.get_text() or '') and e.name in ['p','span','td','dd','div']]
    if elems:
        for e in elems[:2]:
            print(f"  [{pat}] <{e.name} class={e.get('class')}> {e.get_text(strip=True)[:100]}")

# ページサイズ
print(f"\npage size: {len(r2.text):,} bytes")

# アドレス含む data-* attributes
print("\ndata-*検索:")
for tag in soup.find_all(attrs={"data-address": True}):
    print(f"  data-address={tag.get('data-address','')}")
for tag in soup.find_all(attrs={"data-lat": True}):
    print(f"  data-lat={tag.get('data-lat','')} data-lng={tag.get('data-lng','')}")
