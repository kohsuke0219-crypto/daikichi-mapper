"""
ステップ11-4: おたからやスクレイパー

API: GET https://www.otakaraya.jp/wp-json/wp/v2/shop
  - area taxonomy ID でフィルタ (area=379 など)
  - acf.map_position.lat/lng で緯度経度直接取得
  - 1都3県 area ID:
      東京都=379, 神奈川県=380, 埼玉県=377, 千葉県=378

都県ごとに 3 req/sec 以下でページネーション取得
"""
from __future__ import annotations
import logging

from .base import CompetitorScraper, TARGET_PREFS

log = logging.getLogger(__name__)

SHOP_API = "https://www.otakaraya.jp/wp-json/wp/v2/shop"
BRAND    = "おたからや"

PREF_AREA_IDS = {
    "東京都":   379,
    "神奈川県": 380,
    "埼玉県":   377,
    "千葉県":   378,
    "茨城県":   374,
}


class OtakarayaScraper(CompetitorScraper):
    brand = BRAND
    sleep_sec = 0.5

    def fetch_stores(self, prefs: list[str] = None) -> list[dict]:
        target = prefs or TARGET_PREFS
        all_stores: list[dict] = []

        for pref in target:
            area_id = PREF_AREA_IDS.get(pref)
            if area_id is None:
                continue

            pref_stores = self._fetch_pref(pref, area_id)
            log.info(f"  [{pref}] {len(pref_stores)} 件")
            all_stores.extend(pref_stores)

        log.info(f"  おたからや 合計: {len(all_stores)} 件")
        return all_stores

    def _fetch_pref(self, pref: str, area_id: int) -> list[dict]:
        stores: list[dict] = []
        page = 1
        while True:
            r = self.get(SHOP_API, params={
                "per_page": 50,
                "page":     page,
                "area":     area_id,
                "_fields":  "id,title,link,acf",
            })
            items = r.json()
            if not items:
                break

            total_pages = int(r.headers.get("X-WP-TotalPages", 1))
            total_items = int(r.headers.get("X-WP-Total", 0))
            if page == 1:
                log.info(f"    {pref}: 全{total_items}件 / {total_pages}ページ")

            for item in items:
                name = item.get("title", {}).get("rendered", "").strip()
                acf  = item.get("acf", {}) or {}
                mp   = acf.get("map_position", {}) or {}

                try:
                    lat = float(mp.get("lat", "")) if mp.get("lat") else None
                    lng = float(mp.get("lng", "")) if mp.get("lng") else None
                except (TypeError, ValueError):
                    lat = lng = None

                stores.append(self.make_record(
                    name=name,
                    brand=BRAND,
                    address="",         # ACFに住所フィールドなし、lat/lngで代替
                    prefecture=pref,
                    detail_url=item.get("link", ""),
                    latitude=lat,
                    longitude=lng,
                ))

            if page >= total_pages:
                break
            page += 1

        return stores
