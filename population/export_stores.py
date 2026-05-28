"""Google スプレッドシートから店舗データを読み込み docs/data/stores.json に出力する。"""
import json
import os
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

OUT_PATH = Path(__file__).parents[1] / "docs" / "data" / "stores.json"


def get_credentials():
    # GitHub Actions: JSON 文字列が環境変数に入っている
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        import json as _json
        info = _json.loads(sa_json.lstrip("﻿"))
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    # ローカル: ファイルパスが環境変数に入っている
    cred_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_file:
        return Credentials.from_service_account_file(cred_file, scopes=SCOPES)
    raise RuntimeError("認証情報が見つかりません")


def export(spreadsheet_id: str) -> None:
    creds = get_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.sheet1

    records = ws.get_all_records()
    stores = []
    for r in records:
        lat = r.get("latitude") or r.get("lat") or ""
        lng = r.get("longitude") or r.get("lng") or ""
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except (ValueError, TypeError):
            continue  # 緯度経度がない行はスキップ

        stores.append({
            "name": r.get("name", ""),
            "prefecture": r.get("prefecture", ""),
            "address": r.get("address", ""),
            "lat": lat_f,
            "lng": lng_f,
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(stores, f, ensure_ascii=False, separators=(",", ":"))

    print(f"stores.json 出力: {OUT_PATH}  ({len(stores)} 件)")


if __name__ == "__main__":
    sid = os.environ.get("SPREADSHEET_ID", "").strip("﻿").strip()
    if not sid:
        raise RuntimeError("SPREADSHEET_ID が設定されていません")
    export(sid)
