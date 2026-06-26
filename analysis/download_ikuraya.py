"""
買取専門店「いくらや」店舗レイヤー用データ生成。

データ元: いくらや公式 店舗一覧 https://ikuraya.jp/shop_area/{region}/{pref}/
  各店は <tr><th class="shop_name"><a>店名</a></th><td class="shop_address">住所</td>...
取得日: 2026-06-16
対象: 既存マップと同じ1都9県（群馬・山梨はいくらや店舗ページ無し=404→自動スキップ）
ジオコード: Google Geocoding API（住所→座標）。キャッシュ analysis/ikuraya_cache.json

出力: docs/data/ikuraya_stores.json  [{name, prefecture, address, lat, lng}]
"""
import json
import logging
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scraper.geocoder import Geocoder

BASE = Path(__file__).parent
OUT = BASE.parent / "docs" / "data" / "ikuraya_stores.json"
CACHE = BASE / "ikuraya_cache.json"
LOG_PATH = BASE / "progress.log"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124"}

# 都県 → (地域slug, 県slug)。既存マップと同じ1都9県
PREF_REGION = {
    "東京都":   ("kanto", "tokyo"),
    "神奈川県": ("kanto", "kanagawa"),
    "埼玉県":   ("kanto", "saitama"),
    "千葉県":   ("kanto", "chiba"),
    "茨城県":   ("kanto", "ibaraki"),
    "栃木県":   ("kanto", "tochigi"),
    "群馬県":   ("kanto", "gunma"),       # 現状404（店舗なし）
    "静岡県":   ("tyubu", "shizuoka"),
    "愛知県":   ("tyubu", "aichi"),
    "山梨県":   ("tyubu", "yamanashi"),   # 現状404（店舗なし）
}


def fetch_pref(pref, region, slug):
    url = f"https://ikuraya.jp/shop_area/{region}/{slug}/"
    r = requests.get(url, headers=H, timeout=30)
    if r.status_code == 404:
        log.info(f"  [{pref}] 店舗ページ無し(404)スキップ")
        return []
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for th in soup.find_all("th", class_="shop_name"):
        row = th.find_parent("tr")
        if not row:
            continue
        name = th.get_text(strip=True)
        addr_td = row.find("td", class_="shop_address")
        addr = addr_td.get_text(strip=True) if addr_td else ""
        if not name or not addr:
            continue
        out.append({"name": name, "prefecture": pref, "address": addr})
    log.info(f"  [{pref}] {len(out)}店")
    return out


def main():
    log.info("=== いくらや 店舗取得 ===")
    cache = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    stores = []
    for pref, (region, slug) in PREF_REGION.items():
        try:
            stores.extend(fetch_pref(pref, region, slug))
        except Exception as e:
            log.warning(f"  [{pref}] 取得失敗: {e}")
        time.sleep(1)

    log.info(f"  スクレイプ計 {len(stores)}店 → ジオコード")
    geocoder = Geocoder(throttle_sec=0.05)
    out = []
    for s in stores:
        addr = s["address"]
        if addr in cache and cache[addr]:
            lat, lng = cache[addr]
        else:
            r = geocoder.geocode(addr)
            if r.latitude is None:
                log.warning(f"  FAILED geocode: {s['name']} / {addr} ({r.status})")
                cache[addr] = None
                continue
            lat, lng = r.latitude, r.longitude
            cache[addr] = [lat, lng]
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        out.append({
            "name": s["name"], "prefecture": s["prefecture"],
            "address": addr, "lat": round(lat, 6), "lng": round(lng, 6),
        })

    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    log.info(f"  保存: {OUT.name} ({len(out)}店, API呼び出し{geocoder.api_call_count})")
    by = {}
    for s in out:
        by[s["prefecture"]] = by.get(s["prefecture"], 0) + 1
    for k, v in sorted(by.items()):
        log.info(f"    {k}: {v}")
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
