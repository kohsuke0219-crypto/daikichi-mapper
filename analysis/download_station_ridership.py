"""
駅レイヤー（クリックで1日乗降客数を表示）用データ生成。

データ元: 国土数値情報 S12「駅別乗降客数データ」FY2021版
  https://nlftp.mlit.go.jp/ksj/gml/data/S12/S12-22/S12-22_GML.zip
  取得日: 2026-06-16。線形(LineString)・全国10,482本。
  主な属性: S12_001=駅名, S12_001g=駅グループコード(同一駅を事業者横断で束ねる),
            S12_002=運営会社, S12_003=路線名, S12_049=2021年の1日乗降客数(人/日)
  ※値は「1日平均乗降人員(最新公開年=2021年度)」。リアルタイムではない。
  ※駅グループ内で事業者別に集計し、最新年の値(>0)を合算して総計とする。
    複数社の共同計上(「○○を含む」)がある大ターミナルは総計が概算になる場合あり。

出力: docs/data/stations_ridership.json
  [{name, lat, lng, total, year, ops:[{op,line,val}]}]  ※対象1都9県のみ
"""
import json
import logging
import zipfile
from pathlib import Path

import requests
import geopandas as gpd

BASE = Path(__file__).parent
GEO = BASE / "geo_data"
GEO.mkdir(exist_ok=True)
OUT = BASE.parent / "docs" / "data" / "stations_ridership.json"
LOG_PATH = BASE / "progress.log"
ZP = GEO / "S12-22_GML.zip"
URL = "https://nlftp.mlit.go.jp/ksj/gml/data/S12/S12-22/S12-22_GML.zip"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

YEAR = 2021
VAL_COL = "S12_049"      # 最新年(2021)の1日乗降客数
# 1都9県を包む全体bbox（lat, lng）
BBOX = {"lat_min": 34.5, "lat_max": 37.25, "lng_min": 136.5, "lng_max": 141.0}


def to_int(v):
    try:
        n = int(round(float(v)))
        return n if n > 0 else 0
    except (ValueError, TypeError):
        return 0


def main():
    log.info("=== 駅別乗降客数(S12) 取得 ===")
    if not ZP.exists() or ZP.stat().st_size < 100000:
        log.info(f"  DL {URL}")
        r = requests.get(URL, timeout=600, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        ZP.write_bytes(r.content)

    with zipfile.ZipFile(ZP) as z:
        gj = [n for n in z.namelist() if n.lower().endswith(".geojson") and "UTF-8" in n][0]
    gdf = gpd.read_file(f"zip://{ZP}!{gj}")
    log.info(f"  全国 {len(gdf)}本")

    # 代表点(centroid)を付与しbboxで1都9県域に絞る
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    cent = gdf.geometry.centroid
    gdf["lat"] = cent.y
    gdf["lng"] = cent.x
    gdf = gdf[(gdf.lat >= BBOX["lat_min"]) & (gdf.lat <= BBOX["lat_max"]) &
              (gdf.lng >= BBOX["lng_min"]) & (gdf.lng <= BBOX["lng_max"])].copy()
    gdf["val"] = gdf[VAL_COL].map(to_int)
    log.info(f"  対象域 {len(gdf)}本")

    # 事業者-駅コード(S12_001c)ごとに代表1本(最大値)へ集約（重複ジオメトリ行の0を除去）
    gdf["grp"] = gdf["S12_001g"].fillna("").astype(str)
    gdf.loc[gdf["grp"] == "", "grp"] = gdf["S12_001c"].astype(str)
    best = {}   # S12_001c -> row(dict)
    for _, r in gdf.iterrows():
        code = str(r["S12_001c"])
        rec = {"grp": r["grp"], "name": str(r["S12_001"]), "op": str(r["S12_002"]),
               "line": str(r["S12_003"]), "val": int(r["val"]),
               "lat": float(r["lat"]), "lng": float(r["lng"])}
        if code not in best or rec["val"] > best[code]["val"]:
            best[code] = rec

    # 駅グループ(S12_001g)ごとに合算＋事業者別内訳
    groups = {}
    for rec in best.values():
        g = groups.setdefault(rec["grp"], {"name": rec["name"], "ops": [], "top": rec})
        g["ops"].append({"op": rec["op"], "line": rec["line"], "val": rec["val"]})
        # 代表駅名・位置は最大値の事業者に合わせる
        if rec["val"] > g["top"]["val"]:
            g["top"] = rec
            g["name"] = rec["name"]

    out = []
    for g in groups.values():
        ops = [o for o in g["ops"] if o["val"] > 0]
        ops.sort(key=lambda o: -o["val"])
        total = sum(o["val"] for o in ops)
        out.append({
            "name": g["name"], "lat": round(g["top"]["lat"], 6), "lng": round(g["top"]["lng"], 6),
            "total": total, "year": YEAR, "ops": ops,
        })
    out.sort(key=lambda s: -s["total"])

    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    withdata = sum(1 for s in out if s["total"] > 0)
    log.info(f"  保存: {OUT.name} ({len(out)}駅 / うち乗降客数あり{withdata}, "
             f"{OUT.stat().st_size//1024}KB)")
    log.info("  上位5駅:")
    for s in out[:5]:
        log.info(f"    {s['name']} {s['total']:,}人/日 ({len(s['ops'])}路線)")
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
