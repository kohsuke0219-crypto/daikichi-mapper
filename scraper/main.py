"""メインスクリプト。スクレイプ → ジオコード → シート書き込みの流れを統括する。

使い方:
    python -m scraper.main --spreadsheet-id <ID>

環境変数:
    GOOGLE_MAPS_API_KEY        Geocoding API 用キー
    GOOGLE_SERVICE_ACCOUNT_JSON サービスアカウント JSON 文字列（Actions 用）
    GOOGLE_APPLICATION_CREDENTIALS サービスアカウント JSON パス（ローカル用）
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict
from pathlib import Path

from scraper.geocoder import GeocodeResult, Geocoder
from scraper.scraper import REGIONS, Store, scrape_all
from scraper.sheets_writer import (
    append_run_log,
    load_existing_geocache,
    open_sheet,
    write_stores,
)

# 都道府県名ゆれの正規化（境界データは「神奈川」等で格納されている）
_PREF_NORMALIZE = {
    "神奈川": "神奈川県", "東京": "東京都", "埼玉": "埼玉県", "千葉": "千葉県",
    "茨城": "茨城県", "栃木": "栃木県", "群馬": "群馬県", "静岡": "静岡県",
    "愛知": "愛知県", "山梨": "山梨県",
}


def _load_city_pref_map() -> dict[str, str]:
    """docs/data/ward_population.geojson から 市区町村名 → 都道府県 のマップを作る。

    住所頭に都道府県が省略された店舗（例:「世田谷区成城…」）の都道府県を
    市区町村名から補完するために使う。
    """
    path = Path(__file__).parents[1] / "docs" / "data" / "ward_population.geojson"
    m: dict[str, str] = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return m
    for feat in data.get("features", []):
        p = feat.get("properties", {})
        city, pref = p.get("city"), p.get("pref")
        if city and pref:
            m[city] = _PREF_NORMALIZE.get(pref, pref)
    return m


def _infer_prefecture(address: str, city_pref_map: dict[str, str]) -> str:
    """住所の先頭にある市区町村名（最長一致）から都道府県を推定する。"""
    a = (address or "").lstrip()
    best = ""
    for city in city_pref_map:
        if len(city) > len(best) and a.startswith(city):
            best = city
    return city_pref_map.get(best, "") if best else ""


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def run(
    spreadsheet_id: str,
    dry_run: bool = False,
    prefecture: str | None = None,
) -> int:
    """全工程を実行する。

    Args:
        prefecture: 取得対象の都道府県。カンマ区切りで複数指定可（例: "東京都,神奈川県"）。
                    None の場合は全店舗を対象にする。

    Returns:
        終了コード（0 = 成功）
    """
    setup_logging()
    logger = logging.getLogger("main")

    # カンマ区切りを分割してリスト化
    prefectures: list[str] = (
        [p.strip() for p in prefecture.split(",") if p.strip()]
        if prefecture else []
    )

    PREF_TO_REGION: dict[str, str] = {
        "北海道": "hokkaido-tohoku",
        "青森県": "hokkaido-tohoku", "岩手県": "hokkaido-tohoku",
        "宮城県": "hokkaido-tohoku", "秋田県": "hokkaido-tohoku",
        "山形県": "hokkaido-tohoku", "福島県": "hokkaido-tohoku",
        "茨城県": "kanto", "栃木県": "kanto", "群馬県": "kanto",
        "埼玉県": "kanto", "千葉県": "kanto", "東京都": "kanto",
        "神奈川県": "kanto",
        "新潟県": "tyubu", "富山県": "tyubu", "石川県": "tyubu",
        "福井県": "tyubu", "山梨県": "tyubu", "長野県": "tyubu",
        "岐阜県": "tyubu", "静岡県": "tyubu", "愛知県": "tyubu",
        "三重県": "kinki-tiku", "滋賀県": "kinki-tiku",
        "京都府": "kinki-tiku", "大阪府": "kinki-tiku",
        "兵庫県": "kinki-tiku", "奈良県": "kinki-tiku",
        "和歌山県": "kinki-tiku",
        "鳥取県": "tyugoku-sikoku", "島根県": "tyugoku-sikoku",
        "岡山県": "tyugoku-sikoku", "広島県": "tyugoku-sikoku",
        "山口県": "tyugoku-sikoku", "徳島県": "tyugoku-sikoku",
        "香川県": "tyugoku-sikoku", "愛媛県": "tyugoku-sikoku",
        "高知県": "tyugoku-sikoku",
        "福岡県": "kyusyu-okinawa", "佐賀県": "kyusyu-okinawa",
        "長崎県": "kyusyu-okinawa", "熊本県": "kyusyu-okinawa",
        "大分県": "kyusyu-okinawa", "宮崎県": "kyusyu-okinawa",
        "鹿児島県": "kyusyu-okinawa", "沖縄県": "kyusyu-okinawa",
    }

    # 指定都道府県が属する地区だけ取得してサイトへの不要なアクセスを削減
    region_slugs: list[str] | None = None
    if prefectures:
        slugs = list({PREF_TO_REGION[p] for p in prefectures if p in PREF_TO_REGION})
        if slugs:
            region_slugs = slugs
            logger.info("Prefecture filter: %s → fetching regions %s", prefectures, slugs)
        else:
            logger.warning("Unknown prefectures %r, fetching all regions", prefectures)

    # 1) サイトをスクレイプ
    logger.info("Step 1/3: Scraping kaitori-daikichi.jp store pages")
    all_stores: list[Store] = list(scrape_all(region_slugs=region_slugs))

    # 住所頭に都道府県が無い店舗（例:「世田谷区成城…」）は市区町村名から補完
    city_pref_map = _load_city_pref_map()
    filled = 0
    for s in all_stores:
        if not s.prefecture:
            inferred = _infer_prefecture(s.address, city_pref_map)
            if inferred:
                s.prefecture = inferred
                filled += 1
    if filled:
        logger.info("Filled %d stores' prefecture from address (missing pref prefix)", filled)

    stores = (
        [s for s in all_stores if s.prefecture in prefectures]
        if prefectures
        else all_stores
    )
    logger.info(
        "Scraped %d stores total, %d after prefecture filter",
        len(all_stores), len(stores),
    )

    if not stores:
        logger.error("No stores found. サイト構造が変わったか、フィルター条件が厳しすぎます。")
        return 1

    # 2) ジオコーディング（キャッシュ活用）
    logger.info("Step 2/3: Geocoding addresses")
    spreadsheet = None
    new_count = 0

    if dry_run:
        logger.info("DRY RUN: skipping geocoding and sheet write. First 3 stores:")
        for s in stores[:3]:
            logger.info("  %s", asdict(s))
        return 0

    geocache: dict[str, GeocodeResult] = {}
    spreadsheet = open_sheet(spreadsheet_id.strip('﻿').strip())
    existing = load_existing_geocache(spreadsheet)
    geocache = {
        addr: GeocodeResult(latitude=lat, longitude=lng, status="OK")
        for addr, (lat, lng) in existing.items()
    }

    geocoder = Geocoder(cache=geocache)
    for s in stores:
        result = geocoder.geocode(s.address)
        s.latitude = result.latitude
        s.longitude = result.longitude
        if result.status != "OK" or result.latitude is None:
            logger.warning("Geocoding failed for %s: %s", s.name, result.status)

    logger.info(
        "Geocoded %d stores (%d new API calls)", len(stores), geocoder.api_call_count
    )

    # 3) シートに書き込み
    logger.info("Step 3/3: Writing to Google Sheets")

    assert spreadsheet is not None
    write_stores(spreadsheet, [asdict(s) for s in stores])

    # 旧データと比較した差分（簡易版: 件数のみ）
    summary = {
        "total_stores": len(stores),
        "geocode_api_calls": geocoder.api_call_count,
        "new_stores": new_count,  # TODO: store_id ベースの厳密な差分検出
        "removed_stores": 0,
    }
    append_run_log(spreadsheet, summary)
    logger.info("Done. Summary: %s", summary)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spreadsheet-id",
        default=os.environ.get("SPREADSHEET_ID", ""),
        help="書き込み先 Google Spreadsheet の ID",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="スクレイプとジオコードのみ行い、シートには書き込まない",
    )
    parser.add_argument(
        "--prefecture",
        default=os.environ.get("PREFECTURE", ""),
        help="取得対象の都道府県（例: 東京都）。省略時は全国。",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.spreadsheet_id:
        parser.error("--spreadsheet-id または環境変数 SPREADSHEET_ID が必要です")

    sys.exit(run(
        args.spreadsheet_id,
        dry_run=args.dry_run,
        prefecture=args.prefecture or None,
    ))


if __name__ == "__main__":
    main()
