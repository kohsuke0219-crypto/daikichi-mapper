"""国土数値情報 N03（行政区域）GeoJSON と人口データを4都県分結合する。

1. MLIT から 東京(13)・神奈川(14)・埼玉(11)・千葉(12) の N03 GML.zip をダウンロード
2. ZIP 内 GeoJSON を抽出して市区町村ポリゴンを取得
3. 4pref_population.csv の小地域データを市区町村レベルに集計
4. GeoJSON の properties に人口データを埋め込んで保存

出力: docs/data/ward_population.geojson
"""
import csv
import io
import json
import time
import zipfile
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

MLIT_BASE = "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2023/N03-20230101_{pref_code}_GML.zip"
PREF_CODES = {"東京都": "13", "神奈川県": "14", "埼玉県": "11", "千葉県": "12"}

POP_CSV   = Path(__file__).parent / "4pref_population.csv"
OUT_GEOJSON = Path(__file__).parents[1] / "docs" / "data" / "ward_population.geojson"

# ---------------------------------------------------------------------------
# 人口データを市区町村レベルに集計
# ---------------------------------------------------------------------------

def load_ward_population(csv_path: Path) -> dict[str, dict]:
    """小地域CSVを読み込み、ward_code (5桁) に集計して返す。"""
    ward: dict[str, dict] = {}
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = row["key_code"]
            if len(key) < 5:
                continue
            ward_code = key[:5]
            if ward_code not in ward:
                ward[ward_code] = {"total_pop": 0, "women_total": 0, "women_40plus": 0}
            ward[ward_code]["total_pop"]   += int(row["total_pop"])
            ward[ward_code]["women_total"] += int(row["women_total"])
            ward[ward_code]["women_40plus"] += int(row["women_40plus"])
    print(f"  人口集計: {len(ward)} 市区町村")
    return ward


# ---------------------------------------------------------------------------
# MLIT GeoJSON のダウンロード & 抽出
# ---------------------------------------------------------------------------

def fetch_pref_features(pref_name: str, pref_code: str) -> list[dict]:
    """1都県分の行政区域フィーチャーリストを返す。"""
    url = MLIT_BASE.format(pref_code=pref_code)
    print(f"  [{pref_name}] ダウンロード: {url}")
    r = requests.get(url, timeout=180, stream=True)
    r.raise_for_status()
    zip_bytes = r.content
    print(f"  [{pref_name}] {len(zip_bytes)//1024} KB 取得")

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        geojson_files = [n for n in zf.namelist() if n.lower().endswith(".geojson")]
        if not geojson_files:
            raise FileNotFoundError(f"{pref_name}: ZIP 内に GeoJSON なし ({zf.namelist()})")
        raw = zf.read(geojson_files[0])

    data = json.loads(raw.decode("utf-8"))
    features = []
    for f in data.get("features", []):
        p = f.get("properties", {})
        code = (p.get("N03_007") or "").strip()
        if not code:
            continue
        f["properties"] = {
            "code": code,
            "pref": (p.get("N03_001") or "").strip(),
            "city": (p.get("N03_004") or "").strip(),
        }
        features.append(f)

    print(f"  [{pref_name}] {len(features)} フィーチャー")
    return features


# ---------------------------------------------------------------------------
# GeoJSON の組み立て & 保存
# ---------------------------------------------------------------------------

def build_and_save(all_features: list[dict], ward_pop: dict[str, dict]) -> None:
    # code 重複排除（飛び地は最初のポリゴンだけ使用）
    seen: set[str] = set()
    deduped: list[dict] = []
    for f in all_features:
        code = f["properties"]["code"]
        if code in seen:
            continue
        seen.add(code)
        deduped.append(f)

    # 人口データをマージ
    matched = 0
    for f in deduped:
        code = f["properties"]["code"]
        pop = ward_pop.get(code, {})
        f["properties"]["total_pop"]   = pop.get("total_pop", 0)
        f["properties"]["women_40plus"] = pop.get("women_40plus", 0)
        f["properties"]["women_total"] = pop.get("women_total", 0)
        if pop:
            matched += 1

    print(f"  マージ: {matched}/{len(deduped)} 市区町村")

    OUT_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_GEOJSON, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": deduped},
                  f, ensure_ascii=False, separators=(",", ":"))

    size = OUT_GEOJSON.stat().st_size
    print(f"  保存: {OUT_GEOJSON}  ({size//1024} KB, {len(deduped)} features)")


# ---------------------------------------------------------------------------
# 座標精度削減（ファイルサイズ削減）
# ---------------------------------------------------------------------------

def round_coords(obj, precision=4):
    if isinstance(obj, list):
        if obj and isinstance(obj[0], (int, float)):
            return [round(v, precision) for v in obj]
        return [round_coords(item, precision) for item in obj]
    return obj


def simplify_geojson() -> None:
    with open(OUT_GEOJSON, encoding="utf-8") as f:
        data = json.load(f)
    before = OUT_GEOJSON.stat().st_size
    for feat in data["features"]:
        geom = feat.get("geometry")
        if geom:
            geom["coordinates"] = round_coords(geom["coordinates"])
    with open(OUT_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    after = OUT_GEOJSON.stat().st_size
    print(f"  簡略化: {before//1024} KB → {after//1024} KB")


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== 4都県 行政区域 GeoJSON 構築 ===")

    print("\n[1] 人口データ集計")
    ward_pop = load_ward_population(POP_CSV)

    print("\n[2] MLIT N03 GeoJSON ダウンロード")
    all_features: list[dict] = []
    for pref_name, pref_code in PREF_CODES.items():
        features = fetch_pref_features(pref_name, pref_code)
        all_features.extend(features)
        time.sleep(1)

    print(f"\n  合計フィーチャー: {len(all_features)}")

    print("\n[3] GeoJSON 構築 & 保存")
    build_and_save(all_features, ward_pop)

    print("\n[4] 座標精度削減")
    simplify_geojson()

    print("\n完了。")
