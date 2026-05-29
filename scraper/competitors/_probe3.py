"""WordPress REST API & なんぼや住所解析の詳細確認"""
import sys, io, re, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36", "Accept-Language": "ja,en;q=0.9"}

def get(url, **kw):
    r = requests.get(url, headers=HEADERS, timeout=30, **kw)
    r.encoding = r.apparent_encoding
    return r

# =============================================
# 1) なんぼや - tab-content から住所抽出
# =============================================
print("=== なんぼや - tab-content 住所抽出 ===")
r = get("https://nanboya.com/shop/tokyo/")
soup = BeautifulSoup(r.text, "html.parser")

sections = soup.find_all("section", class_="store-detail")
print(f"store-detail sections: {len(sections)}")
for sec in sections[:3]:
    name = sec.find("h3", class_="shopname-heading")
    name_txt = name.get_text(strip=True) if name else ""
    tab = sec.find("div", class_="tab-content")
    tab_txt = tab.get_text(separator="\n", strip=True) if tab else ""
    # 住所行を抽出: 〒 または 東京都 を含む行
    lines = [l.strip() for l in tab_txt.splitlines() if l.strip()]
    addr = next((l for l in lines if "〒" in l or "東京都" in l), "")
    print(f"  名前: {name_txt}")
    print(f"  住所: {addr}")
    print(f"  tab_txt: {tab_txt[:150]}")
    print()

# 神奈川・埼玉・千葉の都道府県ページURL確認
for pref, slug in [("神奈川","kanagawa"),("埼玉","saitama"),("千葉","chiba")]:
    r2 = get(f"https://nanboya.com/shop/{slug}/")
    soup2 = BeautifulSoup(r2.text, "html.parser")
    secs = soup2.find_all("section", class_="store-detail")
    print(f"{pref}: {len(secs)} 件")

# =============================================
# 2) バイセル WordPress REST API
# =============================================
print("\n=== バイセル WP REST API ===")
r3 = get("https://buysell-kaitori.com/wp-json/wp/v2/shop?per_page=3&page=1")
print(f"status: {r3.status_code}")
if r3.status_code == 200:
    shops = r3.json()
    print(f"count: {len(shops)}")
    if shops:
        s = shops[0]
        print(f"keys: {list(s.keys())}")
        print(f"title: {s.get('title',{}).get('rendered','')[:60]}")
        print(f"link: {s.get('link','')[:80]}")
        # meta/ACF fields
        if 'meta' in s:
            print(f"meta: {s['meta']}")
        if 'acf' in s:
            print(f"acf: {json.dumps(s['acf'], ensure_ascii=False)[:300]}")
    # 総件数はヘッダーに
    total = r3.headers.get('X-WP-Total', '?')
    pages = r3.headers.get('X-WP-TotalPages', '?')
    print(f"X-WP-Total: {total}, X-WP-TotalPages: {pages}")

# ACF追加フィールドを確認
r4 = get("https://buysell-kaitori.com/wp-json/wp/v2/shop?per_page=1&_fields=id,title,link,acf,meta,content")
if r4.status_code == 200:
    data = r4.json()
    if data:
        print("\n--- フィールド詳細 ---")
        d = data[0]
        for k, v in d.items():
            val = str(v)[:200]
            print(f"  {k}: {val}")

# =============================================
# 3) おたからや - WP REST API + sitemap
# =============================================
print("\n=== おたからや WP REST API ===")
r5 = get("https://www.otakaraya.jp/wp-json/wp/v2/shop?per_page=3&page=1")
print(f"status: {r5.status_code}")
if r5.status_code == 200:
    shops5 = r5.json()
    print(f"count: {len(shops5)}")
    total5 = r5.headers.get('X-WP-Total','?')
    pages5 = r5.headers.get('X-WP-TotalPages','?')
    print(f"X-WP-Total: {total5}, X-WP-TotalPages: {pages5}")
    if shops5:
        s5 = shops5[0]
        print(f"keys: {list(s5.keys())}")
        print(f"title: {s5.get('title',{}).get('rendered','')[:60]}")
        for k in ['acf','meta','content','excerpt']:
            if k in s5:
                print(f"  {k}: {str(s5[k])[:300]}")

# sitemap からの店舗URL件数確認
print("\n=== おたからや shop-sitemap.xml ===")
r6 = get("https://www.otakaraya.jp/shop-sitemap.xml")
print(f"status: {r6.status_code}, size: {len(r6.text)}")
# 1都3県のURL数カウント
prefs = {"tokyo":"東京","kanagawa":"神奈川","saitama":"埼玉","chiba":"千葉"}
for slug, name in prefs.items():
    count = r6.text.count(f"/shop/{slug}/")
    # area URLs
    area_count = r6.text.count(f"/area/{slug}/")
    print(f"  {name}: /shop/{slug}/ = {count}件, /area/{slug}/ = {area_count}件")
print(f"  shop-sitemap URL総数: {r6.text.count('<loc>')}")
