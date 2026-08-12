"""
ステップ11-3: バイセルスクレイパー

API: GET https://buysell-kaitori.com/wp-json/wp/v2/store_post
  - 全164店舗、2ページ（per_page=100）
  - geolocation: {lat, lng} フィールドで緯度経度直接取得
  - ジオコーディング不要

都道府県の判定:
  /bsportal/v1/cities?pref=東京都 等で各都道府県の市区町村リストを取得し、
  store_post のタイトルと照合して判定。
  照合失敗時は lat/lng の地理的範囲で判定。
"""
from __future__ import annotations
import logging
import math

from .base import CompetitorScraper, TARGET_PREFS

log = logging.getLogger(__name__)

STORE_API  = "https://buysell-kaitori.com/wp-json/wp/v2/store_post"
CITIES_API = "https://buysell-kaitori.com/wp-json/bsportal/v1/cities"
BRAND      = "バイセル"

# 1都3県の地理的バウンディングボックス（概算）
PREF_BOUNDS = {
    "東京都":   {"lat_min": 35.50, "lat_max": 35.90, "lon_min": 138.95, "lon_max": 139.92},
    "神奈川県": {"lat_min": 35.12, "lat_max": 35.70, "lon_min": 138.93, "lon_max": 139.77},
    "埼玉県":   {"lat_min": 35.75, "lat_max": 36.29, "lon_min": 138.72, "lon_max": 139.95},
    "千葉県":   {"lat_min": 35.18, "lat_max": 35.95, "lon_min": 139.72, "lon_max": 140.90},
    "茨城県":   {"lat_min": 35.85, "lat_max": 36.95, "lon_min": 139.66, "lon_max": 140.88},
    "栃木県":   {"lat_min": 36.20, "lat_max": 37.16, "lon_min": 139.32, "lon_max": 140.30},
    "群馬県":   {"lat_min": 35.98, "lat_max": 37.06, "lon_min": 138.40, "lon_max": 139.67},
    "静岡県":   {"lat_min": 34.57, "lat_max": 35.66, "lon_min": 137.45, "lon_max": 139.18},
    "愛知県":   {"lat_min": 34.57, "lat_max": 35.43, "lon_min": 136.67, "lon_max": 137.84},
    "山梨県":   {"lat_min": 35.17, "lat_max": 35.98, "lon_min": 138.18, "lon_max": 139.16},
    "長野県":   {"lat_min": 35.20, "lat_max": 37.03, "lon_min": 137.32, "lon_max": 138.75},
}


def guess_pref_from_latlon(lat: float, lng: float) -> str:
    """lat/lng から都道府県を推定（重複エリアは最近の都市中心で決定）"""
    centers = {
        "東京都":   (35.689, 139.692),
        "神奈川県": (35.448, 139.643),
        "埼玉県":   (35.858, 139.649),
        "千葉県":   (35.605, 140.123),
        "茨城県":   (36.342, 140.447),
        "栃木県":   (36.566, 139.884),
        "群馬県":   (36.391, 139.061),
        "静岡県":   (34.977, 138.383),
        "愛知県":   (35.180, 136.907),
        "山梨県":   (35.664, 138.568),
        "長野県":   (36.200, 138.000),
    }
    # まずバウンディングボックスで候補を絞る
    cands = []
    for pref, b in PREF_BOUNDS.items():
        if b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lng <= b["lon_max"]:
            cy, cx = centers[pref]
            dist = math.hypot(lat - cy, lng - cx)
            cands.append((dist, pref))
    if not cands:
        return ""
    cands.sort()
    return cands[0][1]


def fetch_cities_map() -> dict[str, str]:
    """都道府県名 → 市区町村セット のマップを返す"""
    import requests
    H = {"User-Agent": "Mozilla/5.0 Windows Chrome/124", "Accept-Language": "ja"}
    result: dict[str, set] = {}
    for pref in TARGET_PREFS:
        try:
            r = requests.post(CITIES_API, headers=H, json={"pref": pref}, timeout=15)
            data = r.json()
            if data.get("success"):
                result[pref] = set(data.get("data", []))
        except Exception:
            pass
    return result


class BuysellScraper(CompetitorScraper):
    brand = BRAND
    sleep_sec = 0.3  # REST API なので短くてOK

    def fetch_stores(self, prefs: list[str] = None) -> list[dict]:
        target = set(prefs or TARGET_PREFS)
        log.info("  バイセル: cities マップ取得")
        cities_map = fetch_cities_map()
        log.info(f"  cities: {[(p, len(v)) for p, v in cities_map.items()]}")

        # --- ページネーション取得 ---
        log.info(f"  バイセル: {STORE_API} (全件取得)")
        all_items = []
        page = 1
        while True:
            r = self.get(STORE_API, params={
                "per_page": 100,
                "page": page,
                "_fields": "id,title,link,geolocation",
            })
            items = r.json()
            if not items:
                break
            all_items.extend(items)
            total_pages = int(r.headers.get("X-WP-TotalPages", 1))
            log.info(f"    page {page}/{total_pages}: {len(items)}件")
            if page >= total_pages:
                break
            page += 1

        log.info(f"  全国 {len(all_items)} 件")

        # --- 1都3県フィルタ & 都道府県判定 ---
        stores: list[dict] = []
        pref_counts: dict[str, int] = {}

        for item in all_items:
            geo = item.get("geolocation") or {}
            lat_raw = geo.get("lat")
            lng_raw = geo.get("lng")
            try:
                lat = float(lat_raw) if lat_raw is not None else None
                lng = float(lng_raw) if lng_raw is not None else None
            except (TypeError, ValueError):
                lat = lng = None

            if lat is None or lng is None:
                continue

            pref = guess_pref_from_latlon(lat, lng)
            if not pref or pref not in target:
                continue

            name = item.get("title", {}).get("rendered", "").strip()
            detail_url = item.get("link", "")

            stores.append(self.make_record(
                name=name,
                brand=BRAND,
                address="",   # JS-rendered で取得不可、lat/lng で代替
                prefecture=pref,
                detail_url=detail_url,
                latitude=lat,
                longitude=lng,
            ))
            pref_counts[pref] = pref_counts.get(pref, 0) + 1

        log.info(f"  1都3県 {len(stores)} 件: {pref_counts}")
        return stores
