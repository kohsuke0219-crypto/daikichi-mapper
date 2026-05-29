"""各社サイト構造調査スクリプト（一時利用）"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en;q=0.9",
}

def get(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.encoding = r.apparent_encoding
    return r

# =============================================
# 1) なんぼや - 東京ページ
# =============================================
print("=== なんぼや /shop/tokyo/ ===")
r = get("https://nanboya.com/shop/tokyo/")
soup = BeautifulSoup(r.text, "html.parser")

# 店舗エントリーの候補を探す
stores_h3 = soup.find_all("h3")
print(f"h3タグ数: {len(stores_h3)}")
for h in stores_h3[:5]:
    print(f"  h3: {h.get_text(strip=True)[:80]}")

# 住所を含むpタグ
addr_ps = [p for p in soup.find_all("p") if "東京都" in p.get_text()]
print(f"\n住所含むpタグ: {len(addr_ps)}")
for p in addr_ps[:3]:
    print(f"  p.class={p.get('class')}: {p.get_text(strip=True)[:100]}")

# 詳細ページリンク
detail_links = [a["href"] for a in soup.find_all("a", href=True) if "/shop/tokyo/" in a["href"] and a["href"] != "/shop/tokyo/"]
print(f"\n詳細ページリンク候補: {len(detail_links)}")
for l in detail_links[:5]:
    print(f"  {l}")

# =============================================
# 2) バイセル - API探索
# =============================================
print("\n=== バイセル - サイト探索 ===")
r2 = get("https://buysell-kaitori.com/shop")
print(f"status: {r2.status_code}, size: {len(r2.text)}")
soup2 = BeautifulSoup(r2.text, "html.parser")

# APIっぽいスクリプトタグを探す
scripts = soup2.find_all("script")
for s in scripts:
    src = s.get("src","")
    txt = s.string or ""
    if any(k in (src+txt) for k in ["api","store","shop","json","endpoint"]):
        print(f"  script src={src[:80]} content[:200]={txt[:200]}")

# meta/dataタグ
print("\ndata-* attributes on key elements:")
for tag in soup2.find_all(True, attrs=lambda a: a and any(k.startswith("data-") for k in a)):
    attrs = {k:v for k,v in tag.attrs.items() if k.startswith("data-")}
    if attrs:
        print(f"  <{tag.name}> {attrs}")
        break  # 1件だけ

# =============================================
# 3) おたからや - 小さいページで構造確認
# =============================================
print("\n=== おたからや - 区ページ (新宿区) ===")
r3 = get("https://www.otakaraya.jp/shop/area/tokyo/shinjuku_ku/")
soup3 = BeautifulSoup(r3.text, "html.parser")
print(f"size: {len(r3.text):,} bytes")

# 店舗名候補
for selector in ["h2","h3","h4",".shop-name",".store-name","[class*=shop]","[class*=store]"]:
    found = soup3.select(selector)
    if found:
        print(f"  selector '{selector}' → {len(found)}件: {found[0].get_text(strip=True)[:60]}")

# 住所候補
addr_elem = [t for t in soup3.find_all(True) if "東京都新宿区" in (t.string or "")]
print(f"\n住所含む要素: {len(addr_elem)}")
for e in addr_elem[:3]:
    print(f"  <{e.name} class={e.get('class')}> {e.get_text(strip=True)[:80]}")

# 都道府県ページでのエリアリンク確認
print("\n=== おたからや - 東京ページ (エリアリンクのみ抽出) ===")
r4 = get("https://www.otakaraya.jp/shop/tokyo/")
print(f"size: {len(r4.text):,} bytes")
soup4 = BeautifulSoup(r4.text, "html.parser")
area_links = [a["href"] for a in soup4.find_all("a", href=True) if "/area/tokyo/" in a["href"]]
area_links = list(dict.fromkeys(area_links))
print(f"エリアリンク: {len(area_links)}件")
for l in area_links[:10]:
    print(f"  {l}")
