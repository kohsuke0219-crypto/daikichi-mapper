"""令和2年国勢調査 小地域 人口データ取得スクリプト（東京・神奈川・埼玉・千葉・茨城）。

出力: population/4pref_population.csv （※茨城県を追加し計5都県を格納）
  - key_code     : 地域コード（9桁以上 = 町丁字レベル）
  - area_name    : 地域名
  - total_pop    : 総人口
  - women_total  : 女性総人口
  - women_40_44 … women_75plus : 各年齢階級の女性人口
  - women_40plus : 40歳以上女性人口（合計）
"""
import csv
import os
import time
from pathlib import Path

import requests

APP_ID = os.environ.get("ESTAT_APP_ID", "")
BASE = "https://api.e-stat.go.jp/rest/3.0/app/json"

# 令和2年 小地域 年齢（5歳階級）・男女別人口 statsDataId
PREF_STATS = {
    "東京都":   "8003006792",
    "神奈川県": "8003006761",
    "埼玉県":   "8003006762",
    "千葉県":   "8003006752",
    "茨城県":   "8003006756",
    "栃木県":   "8003006769",
    "群馬県":   "8003006778",
    "静岡県":   "8003006767",
    "愛知県":   "8003006757",
    "山梨県":   "8003006758",
    "長野県":   "8003006775",
}

# 取得する cat01 コード
CAT01_CODES = [
    "0010",  # 総数（総人口）
    "0410",  # 女の総数
    "0500",  # 女40-44歳
    "0510",  # 女45-49歳
    "0520",  # 女50-54歳
    "0530",  # 女55-59歳
    "0540",  # 女60-64歳
    "0550",  # 女65-69歳
    "0560",  # 女70-74歳
    "0600",  # 女75歳以上
]

# 40歳以上女性を構成する cat01 コード
WOMEN_40PLUS_CODES = ["0500", "0510", "0520", "0530", "0540", "0550", "0560", "0600"]

CAT01_TO_COL = {
    "0010": "total_pop",
    "0410": "women_total",
    "0500": "women_40_44",
    "0510": "women_45_49",
    "0520": "women_50_54",
    "0530": "women_55_59",
    "0540": "women_60_64",
    "0550": "women_65_69",
    "0560": "women_70_74",
    "0600": "women_75plus",
}

CSV_COLUMNS = (
    ["key_code", "area_name", "total_pop", "women_total"]
    + [CAT01_TO_COL[c] for c in WOMEN_40PLUS_CODES]
    + ["women_40plus"]
)

OUT_DIR = Path(__file__).parent
OUT_PATH = OUT_DIR / "4pref_population.csv"


# ---------------------------------------------------------------------------
# API アクセス
# ---------------------------------------------------------------------------

def _get(params: dict, timeout: int = 60) -> dict:
    r = requests.get(f"{BASE}/getStatsData", params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_pref(stats_data_id: str, pref_name: str) -> tuple[list[dict], dict[str, str]]:
    """1都県分のレコードを取得し (values, area_name_map) を返す。"""
    base_params = {
        "appId": APP_ID,
        "statsDataId": stats_data_id,
        "cdCat01": ",".join(CAT01_CODES),
        "limit": 100000,
    }

    all_values: list[dict] = []
    area_name_map: dict[str, str] = {}
    start_position = 1
    total: int | None = None

    while True:
        params = {**base_params, "startPosition": start_position}
        print(f"  [API {pref_name}] startPosition={start_position} ...", end=" ", flush=True)

        data = _get(params)
        stat = data.get("GET_STATS_DATA", {}).get("STATISTICAL_DATA", {})
        result_inf = stat.get("RESULT_INF", {})

        if total is None:
            total = int(result_inf.get("TOTAL_NUMBER", 0))
            for obj in stat.get("CLASS_INF", {}).get("CLASS_OBJ", []):
                if obj.get("@id") == "area":
                    classes = obj.get("CLASS", [])
                    if isinstance(classes, dict):
                        classes = [classes]
                    for c in classes:
                        area_name_map[c.get("@code", "")] = c.get("@name", "")
            print(f"全{total}件 / 地域名{len(area_name_map)}件")
        else:
            print(f"→ {result_inf.get('TO_NUMBER')}件目まで")

        values = stat.get("DATA_INF", {}).get("VALUE", [])
        if isinstance(values, dict):
            values = [values]
        all_values.extend(values)

        next_key = result_inf.get("NEXT_KEY")
        if not next_key or len(all_values) >= total:
            break
        start_position = int(next_key)
        time.sleep(0.3)

    print(f"  [{pref_name}] 取得完了: {len(all_values)}件")
    return all_values, area_name_map


def fetch_all_prefs() -> tuple[list[dict], dict[str, str]]:
    """全4県分のデータを取得して統合する。"""
    combined_values: list[dict] = []
    combined_names: dict[str, str] = {}
    for pref_name, stats_id in PREF_STATS.items():
        values, names = fetch_pref(stats_id, pref_name)
        combined_values.extend(values)
        combined_names.update(names)
        time.sleep(1)  # 県間のインターバル
    return combined_values, combined_names


# ---------------------------------------------------------------------------
# データ処理
# ---------------------------------------------------------------------------

def pivot(values: list[dict], area_name_map: dict[str, str]) -> list[dict]:
    """VALUE リストを area_code ごとに集計してリストを返す。"""
    # area_code -> {cat01_code: int}
    area_data: dict[str, dict[str, int]] = {}

    for v in values:
        area_code = v.get("@area", "")
        cat01 = v.get("@cat01", "")
        val_str = v.get("$", "")

        if cat01 not in CAT01_CODES:
            continue

        if area_code not in area_data:
            area_data[area_code] = {}

        try:
            area_data[area_code][cat01] = int(val_str)
        except (ValueError, TypeError):
            area_data[area_code][cat01] = 0  # "-" (秘匿) は 0 扱い

    rows = []
    for area_code, vals in area_data.items():
        # 9桁以上 = 大字・町丁字レベル (5桁=市区町村 は除外)
        if len(area_code) < 9:
            continue

        women_40plus = sum(vals.get(c, 0) for c in WOMEN_40PLUS_CODES)

        row: dict = {
            "key_code": area_code,
            "area_name": area_name_map.get(area_code, ""),
            "total_pop": vals.get("0010", 0),
            "women_total": vals.get("0410", 0),
            "women_40_44": vals.get("0500", 0),
            "women_45_49": vals.get("0510", 0),
            "women_50_54": vals.get("0520", 0),
            "women_55_59": vals.get("0530", 0),
            "women_60_64": vals.get("0540", 0),
            "women_65_69": vals.get("0550", 0),
            "women_70_74": vals.get("0560", 0),
            "women_75plus": vals.get("0600", 0),
            "women_40plus": women_40plus,
        }
        rows.append(row)

    # key_code でソート
    rows.sort(key=lambda r: r["key_code"])
    return rows


def save_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  CSV 保存: {path}  ({len(rows)}件)")


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not APP_ID:
        raise RuntimeError("環境変数 ESTAT_APP_ID が設定されていません")

    print("=== 令和2年国勢調査 4都県 小地域 年齢・男女別人口 取得 ===")
    print(f"対象: {list(PREF_STATS.keys())}")
    print()

    values, area_name_map = fetch_all_prefs()
    rows = pivot(values, area_name_map)

    total_areas = len(rows)
    sample = rows[:3]
    print(f"\n  町丁字レベル行数: {total_areas}")
    for r in sample:
        print(f"  {r['key_code']} {r['area_name']}: 総人口={r['total_pop']}, 女40+={r['women_40plus']}")

    save_csv(rows, OUT_PATH)
    print("\n完了。")
