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
import logging
import os
import sys
from dataclasses import asdict

from scraper.geocoder import GeocodeResult, Geocoder
from scraper.scraper import Store, scrape_all
from scraper.sheets_writer import (
    append_run_log,
    load_existing_geocache,
    open_sheet,
    write_stores,
)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def run(spreadsheet_id: str, dry_run: bool = False) -> int:
    """全工程を実行する。

    Returns:
        終了コード（0 = 成功）
    """
    setup_logging()
    logger = logging.getLogger("main")

    # 1) サイトをスクレイプ
    logger.info("Step 1/3: Scraping kaitori-daikichi.jp store pages")
    stores: list[Store] = list(scrape_all())
    logger.info("Scraped %d stores total", len(stores))

    if not stores:
        logger.error("No stores scraped. サイト構造が変わった可能性があります。")
        return 1

    # 2) ジオコーディング（キャッシュ活用）
    logger.info("Step 2/3: Geocoding addresses")
    spreadsheet = None
    geocache: dict[str, GeocodeResult] = {}

    if not dry_run:
        spreadsheet = open_sheet(spreadsheet_id)
        existing = load_existing_geocache(spreadsheet)
        # 既存シートの (lat, lng) を Geocoder のキャッシュ形式に変換
        geocache = {
            addr: GeocodeResult(latitude=lat, longitude=lng, status="OK")
            for addr, (lat, lng) in existing.items()
        }

    geocoder = Geocoder(cache=geocache)
    new_count = 0
    for s in stores:
        result = geocoder.geocode(s.address)
        s.latitude = result.latitude
        s.longitude = result.longitude
        if result.status == "OK" and result.latitude is not None:
            # キャッシュヒットだったかは Geocoder.api_call_count で別途追跡
            pass
        else:
            logger.warning("Geocoding failed for %s: %s", s.name, result.status)

    logger.info(
        "Geocoded %d stores (%d new API calls)", len(stores), geocoder.api_call_count
    )

    # 3) シートに書き込み
    logger.info("Step 3/3: Writing to Google Sheets")
    if dry_run:
        logger.info("DRY RUN: not writing to sheet. First 3 stores:")
        for s in stores[:3]:
            logger.info("  %s", asdict(s))
        return 0

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
    args = parser.parse_args()

    if not args.dry_run and not args.spreadsheet_id:
        parser.error("--spreadsheet-id または環境変数 SPREADSHEET_ID が必要です")

    sys.exit(run(args.spreadsheet_id, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
