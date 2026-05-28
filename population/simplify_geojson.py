"""GeoJSON の座標精度を下げてファイルサイズを削減する。"""
import json
from pathlib import Path

IN  = Path(__file__).parents[1] / "docs" / "data" / "tokyo_ward_population.geojson"
OUT = IN  # 上書き（バックアップは省略）

PRECISION = 4  # 小数点以下 4 桁 (約 11m 精度で十分)


def round_coords(obj):
    if isinstance(obj, list):
        if obj and isinstance(obj[0], (int, float)):
            return [round(v, PRECISION) for v in obj]
        return [round_coords(item) for item in obj]
    return obj


with open(IN, encoding="utf-8") as f:
    data = json.load(f)

before = IN.stat().st_size

for feat in data["features"]:
    geom = feat.get("geometry")
    if geom:
        geom["coordinates"] = round_coords(geom["coordinates"])

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

after = OUT.stat().st_size
print(f"圧縮: {before//1024} KB → {after//1024} KB  ({100*after//before}%)")
