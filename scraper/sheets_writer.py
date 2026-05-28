"""Google Sheets への書き込みモジュール。

gspread を使い、スプレッドシートにフルリプレースで書き込む。
Looker Studio はこのシートをデータソースとして自動同期する。

設計判断:
- 「差分 upsert」より「フル書き換え」のほうが状態管理が単純で安全。
- 1900行程度なら一括書き込みでも数秒で終わるので、複雑にする意味がない。
- 過去履歴を残したい場合は別途 history シートを用意する想定（後述）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

# Looker Studio が読みやすいよう、カラム順を固定する
COLUMNS = [
    "store_id",
    "name",
    "region",
    "prefecture",
    "address",
    "latitude",
    "longitude",
    "closed_days",
    "business_hours",
    "phone",
    "detail_url",
    "map_url",
    "content_hash",
    "updated_at",
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def open_sheet(spreadsheet_id: str, sa_json_path: str | None = None) -> gspread.Spreadsheet:
    """サービスアカウント認証でスプレッドシートを開く。

    Args:
        spreadsheet_id: 対象スプレッドシートの ID（URL の /d/ の後ろ）
        sa_json_path: サービスアカウント JSON のパス。
            None の場合は環境変数 GOOGLE_APPLICATION_CREDENTIALS を使う。
    """
    if sa_json_path:
        creds = Credentials.from_service_account_file(sa_json_path, scopes=SCOPES)
    else:
        # GitHub Actions では GOOGLE_APPLICATION_CREDENTIALS にファイルパスを書き出して
        # おく運用にする（後述のワークフロー参照）
        creds, _ = _default_creds()
    client = gspread.authorize(creds)
    return client.open_by_key(spreadsheet_id)


def _default_creds():
    """環境変数のサービスアカウント JSON を読み込む。"""
    import json
    import os

    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        info = json.loads(sa_json)
        return Credentials.from_service_account_info(info, scopes=SCOPES), None

    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if path:
        return Credentials.from_service_account_file(path, scopes=SCOPES), None

    raise RuntimeError(
        "認証情報が見つかりません。GOOGLE_SERVICE_ACCOUNT_JSON または "
        "GOOGLE_APPLICATION_CREDENTIALS を設定してください。"
    )


def load_existing_geocache(
    spreadsheet: gspread.Spreadsheet, worksheet_name: str = "stores"
) -> dict[str, tuple[float, float]]:
    """既存シートから {住所: (lat, lng)} を読み出してジオコードキャッシュにする。"""
    try:
        ws = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        return {}

    records = ws.get_all_records()
    cache: dict[str, tuple[float, float]] = {}
    for row in records:
        addr = str(row.get("address", "")).strip()
        lat = row.get("latitude")
        lng = row.get("longitude")
        if not addr or lat in (None, "", "None") or lng in (None, "", "None"):
            continue
        try:
            cache[addr] = (float(lat), float(lng))
        except (TypeError, ValueError):
            continue
    logger.info("Loaded %d cached geocodes from existing sheet", len(cache))
    return cache


def write_stores(
    spreadsheet: gspread.Spreadsheet,
    stores_dicts: list[dict[str, Any]],
    worksheet_name: str = "stores",
) -> None:
    """店舗データをシートにフル書き込みする。

    既存シートをクリアしてからヘッダ＋データを一括書き込み。
    """
    try:
        ws = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=worksheet_name, rows=2500, cols=len(COLUMNS))

    now = datetime.now().isoformat(timespec="seconds")

    rows: list[list[Any]] = [COLUMNS]
    for d in stores_dicts:
        # latitude/longitude が None の場合は空文字に揃える
        # （Looker Studio の地理型カラムが None でエラーになるのを防ぐ）
        row = []
        for col in COLUMNS:
            if col == "updated_at":
                row.append(now)
                continue
            val = d.get(col, "")
            if val is None:
                val = ""
            row.append(val)
        rows.append(row)

    ws.clear()
    # value_input_option="RAW" で文字列として入れる。緯度経度の少数も精度を失わない。
    ws.update(values=rows, range_name="A1", value_input_option="RAW")
    logger.info("Wrote %d rows to sheet %r", len(rows) - 1, worksheet_name)


def append_run_log(
    spreadsheet: gspread.Spreadsheet,
    summary: dict[str, Any],
    worksheet_name: str = "run_log",
) -> None:
    """実行サマリを run_log シートに追記する。差分追跡用。"""
    try:
        ws = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=10)
        ws.append_row(
            ["run_at", "total_stores", "new_stores", "removed_stores", "geocode_api_calls", "notes"]
        )

    ws.append_row(
        [
            datetime.now().isoformat(timespec="seconds"),
            summary.get("total_stores", 0),
            summary.get("new_stores", 0),
            summary.get("removed_stores", 0),
            summary.get("geocode_api_calls", 0),
            summary.get("notes", ""),
        ]
    )
