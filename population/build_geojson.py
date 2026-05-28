"""国土数値情報 N03（行政区域）GML を GeoJSON に変換し、人口データを結合する。

1. MLIT から東京都の N03 GML.zip をダウンロード
2. GML をパースして市区町村ポリゴン + N03_007（行政区域コード）を抽出
3. tokyo_population.csv の小地域データを市区町村レベルに集計
4. GeoJSON の properties に人口データを埋め込んで保存

出力: population/tokyo_ward_population.geojson
"""
import csv
import io
import json
import zipfile
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

MLIT_URL = "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2023/N03-20230101_13_GML.zip"
POP_CSV = Path(__file__).parent / "tokyo_population.csv"
OUT_GEOJSON = Path(__file__).parent / "tokyo_ward_population.geojson"

# ---------------------------------------------------------------------------
# 人口データを市区町村レベルに集計
# ---------------------------------------------------------------------------

def load_ward_population(csv_path: Path) -> dict[str, dict]:
    """小地域CSVを読み込み、ward_code (5桁) に集計して返す。"""
    ward = {}
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = row["key_code"]
            if len(key) < 5:
                continue
            ward_code = key[:5]
            if ward_code not in ward:
                ward[ward_code] = {
                    "total_pop": 0,
                    "women_total": 0,
                    "women_40plus": 0,
                }
            ward[ward_code]["total_pop"]  += int(row["total_pop"])
            ward[ward_code]["women_total"] += int(row["women_total"])
            ward[ward_code]["women_40plus"] += int(row["women_40plus"])
    print(f"  人口集計: {len(ward)} 市区町村")
    return ward


# ---------------------------------------------------------------------------
# GML をダウンロード & パース
# ---------------------------------------------------------------------------

def download_gml() -> bytes:
    print(f"  ダウンロード: {MLIT_URL}")
    r = requests.get(MLIT_URL, timeout=180, stream=True)
    r.raise_for_status()
    data = r.content
    print(f"  取得完了: {len(data)//1024} KB")
    return data


def extract_geojson_from_zip(zip_bytes: bytes) -> list[dict]:
    """ZIP 内の GeoJSON ファイルを直接読み込んで features を返す。"""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        print(f"  ZIP 内ファイル: {names}")
        geojson_files = [n for n in names if n.lower().endswith(".geojson")]
        if not geojson_files:
            raise FileNotFoundError(f"ZIP 内に GeoJSON ファイルが見つかりません: {names}")
        raw = zf.read(geojson_files[0])

    print(f"  GeoJSON サイズ: {len(raw)//1024} KB")
    data = json.loads(raw.decode("utf-8"))

    # properties を整形: N03_007 → code, N03_001 → pref, N03_004 → city
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

    print(f"  フィーチャー数: {len(features)}")
    return features


# ---------------------------------------------------------------------------
# GeoJSON の組み立て & 保存
# ---------------------------------------------------------------------------

def build_and_save(features: list[dict], ward_pop: dict[str, dict]) -> None:
    """population データを features の properties にマージして GeoJSON を保存。"""
    # code が重複する場合（飛び地など）は最初だけ使う
    seen: set[str] = set()
    deduped: list[dict] = []
    for f in features:
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
        f["properties"]["total_pop"] = pop.get("total_pop", 0)
        f["properties"]["women_40plus"] = pop.get("women_40plus", 0)
        f["properties"]["women_total"] = pop.get("women_total", 0)
        if pop:
            matched += 1

    print(f"  マージ: {matched}/{len(deduped)} 市区町村にデータが対応")

    geojson = {"type": "FeatureCollection", "features": deduped}
    with open(OUT_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, separators=(",", ":"))

    size = OUT_GEOJSON.stat().st_size
    print(f"  GeoJSON 保存: {OUT_GEOJSON}  ({size//1024} KB, {len(deduped)} features)")


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== 行政区域 GeoJSON 構築 ===")

    print("\n[1] 人口データ集計")
    ward_pop = load_ward_population(POP_CSV)

    print("\n[2] MLIT N03 GML ダウンロード")
    zip_bytes = download_gml()

    print("\n[3] GeoJSON 抽出")
    features = extract_geojson_from_zip(zip_bytes)

    if not features:
        raise RuntimeError("フィーチャーが見つかりませんでした。GML 構造を確認してください")

    # 先頭 3 件のプロパティを確認
    print("\n  先頭 3 フィーチャー:")
    for f in features[:3]:
        print(f"    {f['properties']}")

    print("\n[4] GeoJSON 構築 & 保存")
    build_and_save(features, ward_pop)

    print("\n完了。")
