"""詳細調査 スクリプト"""
import sys, io, re, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en;q=0.9",
}

def get(url, **kw):
    r = requests.get(url, headers=HEADERS, timeout=30, **kw)
    r.encoding = r.apparent_encoding
    return r

# =============================================
# 1) なんぼや: h3周辺の構造
# =============================================
print("=== なんぼや - h3周辺の住所構造 ===")
r = get("https://nanboya.com/shop/tokyo/")
soup = BeautifulSoup(r.text, "html.parser")

# h3のある店舗エントリーを1件確認
first_h3 = soup.find("h3")
if first_h3:
    parent = first_h3.parent
    print(f"親要素: <{parent.name} class={parent.get('class')}>")
    # 兄弟要素を全部見る
    for sib in parent.children:
        if hasattr(sib, 'name') and sib.name:
            txt = sib.get_text(strip=True)[:80]
            print(f"  <{sib.name} class={sib.get('class')}> {txt}")

# 住所は「住所:」形式か確認
addr_pattern = [p for p in soup.find_all(True) if "住" in (p.get_text() or "") and "〒" in (p.get_text() or "")]
print(f"\n住所(〒含む)要素: {len(addr_pattern)}")
for e in addr_pattern[:3]:
    print(f"  <{e.name} class={e.get('class')}> {e.get_text(strip=True)[:100]}")

# =============================================
# 2) バイセル - WordPress REST API / shop.js 確認
# =============================================
print("\n=== バイセル - WordPress REST API 探索 ===")
# WP REST API
r2 = get("https://buysell-kaitori.com/wp-json/wp/v2/posts?per_page=5")
print(f"WP REST posts: {r2.status_code}")

# カスタム投稿タイプ探索
for cpt in ["shop","store","spot","branch"]:
    r3 = get(f"https://buysell-kaitori.com/wp-json/wp/v2/{cpt}?per_page=3")
    if r3.status_code == 200:
        try:
            data = r3.json()
            print(f"  /wp-json/wp/v2/{cpt}: OK ({len(data)}件) first={data[0].get('title',{}).get('rendered','')[:50] if data else 'empty'}")
        except: pass
    else:
        print(f"  /wp-json/wp/v2/{cpt}: {r3.status_code}")

# shop.js の内容確認
r4 = get("https://buysell-kaitori.com/wp-content/themes/bsportal/assets/js/new/shop.js")
js = r4.text[:3000]
print(f"\nshop.js先頭3000文字:")
print(js)

# =============================================
# 3) おたからや - 全国一括JSONの可能性
# =============================================
print("\n=== おたからや - JSON/API探索 ===")
# サイトマップからURL確認
r5 = get("https://www.otakaraya.jp/sitemap.xml")
print(f"sitemap.xml: {r5.status_code}, size={len(r5.text)}")
print(r5.text[:1000])

# 店舗一覧API候補
for ep in ["/api/shops", "/shop.json", "/wp-json/wp/v2/shop", "/shops/json"]:
    r6 = get(f"https://www.otakaraya.jp{ep}")
    print(f"  {ep}: {r6.status_code}")

# 新宿区ページの h3 ~ span 構造をサンプル確認（最初の3件のみ）
print("\n=== おたからや 新宿区 - 最初の3店舗構造 ===")
# すでにダウンロード済みなので小さなサンプルで確認
r7 = get("https://www.otakaraya.jp/shop/area/tokyo/shinjuku_ku/")
soup7 = BeautifulSoup(r7.text, "html.parser")

h3s = soup7.find_all("h3")
print(f"h3 total: {len(h3s)}")
for h3 in h3s[:5]:
    name = h3.get_text(strip=True)
    parent = h3.parent
    # 住所をspanから探す
    spans = parent.find_all("span") if parent else []
    addr = next((s.get_text(strip=True) for s in spans if "東京" in s.get_text() or "〒" in s.get_text()), "")
    # dataタグ探索
    data_attrs = {k:v for k,v in parent.attrs.items() if k.startswith("data-")} if parent else {}
    print(f"  店名: {name[:40]} | 住所: {addr[:50]} | data={data_attrs}")
