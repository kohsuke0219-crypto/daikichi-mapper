"""
市区町村の役所（市役所・区役所・町村役場）レイヤー用データ生成。

ward_population.geojson の各市区町村について役所名を組み立て、
Google Geocoding API で座標化する。1市区町村につき1役所。

命名ルール（city末尾で判定）:
  市 → 市役所 / 区 → 区役所 / 町 → 役場（町役場）/ 村 → 役場（村役場）
  ※政令市の区は city="横浜市鶴見区" のようにフル名なので "横浜市鶴見区役所" になる
  ※無人地・境界地（…島/…岩/埋立地/所属未定地 等）はスキップ

データ元: 役所名を Google Geocoding API でジオコード（取得日 2026-06-11）
キャッシュ: analysis/townhalls_cache.json（クエリ→[lat,lng]）で再実行時のAPI節約
出力: docs/data/townhalls.json  [{code, name, pref, city, lat, lng}]
"""
import json
import logging
import os
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scraper.geocoder import Geocoder

BASE = Path(__file__).parent
WARD = BASE.parent / "docs" / "data" / "ward_population.geojson"
OUT = BASE.parent / "docs" / "data" / "townhalls.json"
CACHE = BASE / "townhalls_cache.json"
LOG_PATH = BASE / "progress.log"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

PREF_NORMALIZE = {"神奈川": "神奈川県", "東京": "東京都", "埼玉": "埼玉県",
                  "千葉": "千葉県", "茨城": "茨城県", "栃木": "栃木県",
                  "群馬": "群馬県", "静岡": "静岡県", "愛知": "愛知県", "山梨": "山梨県"}


def office_name(city: str) -> str | None:
    """city末尾から役所名を組み立て。対象外はNone。"""
    if not city:
        return None
    last = city[-1]
    if last in ("市", "区"):
        return city + "役所"
    if last in ("町", "村"):
        return city + "役場"
    return None   # 無人地・境界地など


def main():
    log.info("=== 市区町村の役所 ジオコード ===")
    data = json.loads(WARD.read_text(encoding="utf-8"))

    cache = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    geocoder = Geocoder(throttle_sec=0.05)
    out = []
    skipped = 0
    seen = set()
    for feat in data["features"]:
        p = feat["properties"]
        code = str(p.get("code", "")).zfill(5)
        if code in seen:
            continue
        pref = PREF_NORMALIZE.get(p.get("pref", ""), p.get("pref", ""))
        city = p.get("city", "")
        name = office_name(city)
        if not name:
            skipped += 1
            continue
        seen.add(code)
        query = f"{pref}{name}"

        if query in cache and cache[query]:
            lat, lng = cache[query]
        else:
            r = geocoder.geocode(query)
            if r.latitude is None:
                log.warning(f"  FAILED {query}: {r.status}")
                cache[query] = None
                continue
            lat, lng = r.latitude, r.longitude
            cache[query] = [lat, lng]
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

        out.append({
            "code": code, "name": name, "pref": pref, "city": city,
            "lat": round(lat, 6), "lng": round(lng, 6),
        })

    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    log.info(f"  保存: {OUT.name} ({len(out)}件 / 対象外スキップ{skipped}件, "
             f"API呼び出し{geocoder.api_call_count})")
    # 県別件数
    by = {}
    for s in out:
        by[s["pref"]] = by.get(s["pref"], 0) + 1
    for k, v in sorted(by.items()):
        log.info(f"    {k}: {v}")
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
