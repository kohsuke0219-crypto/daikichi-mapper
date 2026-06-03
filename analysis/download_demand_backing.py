"""
需要の裏付け 市区町村別データ取得（戦略②の複合指標ソース）

データソース: e-Stat 社会・人口統計体系 市区町村データ「C 経済基盤」
              statsDataId=0000020103（市区町村データ 基礎データ）取得日: 2026-06-03
指標(cat01):
  (a) 漁業就業者数        C3125   ← 漁業・水産の厚み（海なし市町村は0）
  (b) 製造業従業者数      C3404   ← 工業町の厚み
  (c) 農業産出額          C3101   ← 農業町の厚み
  (d) 商業従業者数(卸+小) C3503   ← 商業集積（旧商家町等の代理指標）

各ソースは独立に取得。後から差し替え可能なよう DEMAND_INDICATORS で定義。
出力: analysis/demand_backing.csv (code, fishery, manufacturing, agriculture, commerce, <each>_year)
"""
import csv
import io
import logging
import os
import sys
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent
LOG_PATH = BASE_DIR / "progress.log"
OUT_CSV  = BASE_DIR / "demand_backing.csv"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

APP_ID = os.environ.get("ESTAT_APP_ID", "")
BASE = "https://api.e-stat.go.jp/rest/3.0/app/json"
STATS_DATA_ID = "0000020103"  # 社会・人口統計体系 市区町村データ C経済基盤

# 後から差し替え可能なソース定義（列名: e-Stat cat01コード）
DEMAND_INDICATORS = {
    "fishery":       "C3125",   # 漁業就業者数
    "manufacturing": "C3404",   # 製造業従業者数
    "agriculture":   "C3101",   # 農業産出額
    "commerce":      "C3503",   # 商業従業者数(卸売+小売)
}

# 対象8都県（コード先頭2桁）
TARGET_PREF_CODES = {"08", "09", "10", "11", "12", "13", "14", "22"}


def fetch_indicator(cat_code: str) -> dict:
    """1指標を全国市区町村分取得し、市区町村コード→(値, 年) を返す（最新年を採用）"""
    result = {}  # code -> (value, year)
    start = 1
    while True:
        params = {
            "appId": APP_ID, "statsDataId": STATS_DATA_ID,
            "cdCat01": cat_code, "limit": 100000, "startPosition": start,
        }
        r = requests.get(f"{BASE}/getStatsData", params=params, timeout=120)
        stat = r.json().get("GET_STATS_DATA", {}).get("STATISTICAL_DATA", {})
        values = stat.get("DATA_INF", {}).get("VALUE", [])
        if isinstance(values, dict):
            values = [values]
        for v in values:
            area = v.get("@area", "")
            if area[:2] not in TARGET_PREF_CODES:
                continue
            year = v.get("@time", "")
            try:
                val = float(v.get("$", ""))
            except (ValueError, TypeError):
                continue
            # 最新年を採用
            if area not in result or year > result[area][1]:
                result[area] = (val, year)
        next_key = stat.get("RESULT_INF", {}).get("NEXT_KEY")
        if not next_key:
            break
        start = int(next_key)
    return result


def main():
    if not APP_ID:
        log.error("ESTAT_APP_ID 未設定"); sys.exit(1)
    log.info("=== 需要の裏付けデータ取得（経済基盤 0000010103）===")

    data = {}  # code -> {source: value, source_year: year}
    for source, cat in DEMAND_INDICATORS.items():
        log.info(f"  [{source}] cat01={cat} 取得中…")
        res = fetch_indicator(cat)
        log.info(f"    {len(res)} 市区町村")
        for code, (val, year) in res.items():
            d = data.setdefault(code, {})
            d[source] = val
            d[f"{source}_year"] = year

    # CSV 出力
    cols = ["code"] + list(DEMAND_INDICATORS.keys()) + [f"{s}_year" for s in DEMAND_INDICATORS]
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for code in sorted(data):
            row = {"code": code}
            for s in DEMAND_INDICATORS:
                row[s] = data[code].get(s, "")
                row[f"{s}_year"] = data[code].get(f"{s}_year", "")
            w.writerow(row)
    log.info(f"  保存: {OUT_CSV.name} ({len(data)} 市区町村)")

    # サマリ
    import statistics
    for s in DEMAND_INDICATORS:
        vals = [data[c][s] for c in data if s in data[c]]
        if vals:
            log.info(f"  {s}: n={len(vals)} max={max(vals):,.0f} median={statistics.median(vals):,.0f}")
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
