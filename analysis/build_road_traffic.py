"""
道路の通行量（自動車交通量）レイヤー用データ生成。

データ元: 令和3年度 道路交通センサス 一般交通量調査（国土交通省）を
  shiwaku 氏が GeoParquet 化したもの（JGD2000）。
  https://github.com/shiwaku/mlit-road-traffic-census-converter (data-v1)
  DL: gh release download data-v1 -R shiwaku/mlit-road-traffic-census-converter -p 'traffic_census_2021_converted.parquet'

抽出: 地図の対象1都10県（市区町村コード上2桁で絞る）。
  高速自動車国道・都市高速・自動車専用道路・路線名に「高速/自動車道」を含むもの、
  および24時間交通量が無い区間は除外（店舗前の通行量として意味がないため）。
出力: docs/data/road_traffic.geojson（EPSG:4326、座標5桁、simplifyで軽量化・10MB目安）
  プロパティ: road, t24, t12, pt, cong, sidewalk, roadside, lanes
"""
import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

BASE = Path(__file__).parent
SRC = BASE / "geo_data" / "traffic_census_2021_converted.parquet"
OUT = BASE.parent / "docs" / "data" / "road_traffic.geojson"
LOG = BASE / "progress.log"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler()])
log = logging.getLogger(__name__)

TARGET_PREF = {8, 9, 10, 11, 12, 13, 14, 19, 20, 22, 23}  # 1都10県
SIMPLIFY_TOL = 0.0006   # 度（約60m）。10MB以内に収まるよう調整（商圏俯瞰用途）
COORD_DECIMALS = 5

C_T24 = "２４時間自動車類交通量（上下合計）／合計（台）"
C_T12 = "昼間１２時間自動車類交通量（上下合計）／合計（台）"
C_PT_UP = "上り／交通量観測地点地名"
C_PT_DN = "下り／交通量観測地点地名"
C_CONG = "混雑度"
C_SIDEWALK = "交通安全施設等／歩道設置率（％）"
C_ROADSIDE = "代表沿道状況"
C_LANES = "車線数"


def _num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _strip_code(s):
    """'4：平地部' → '平地部'（コード接頭辞を除去）"""
    s = str(s or "").strip()
    if "：" in s:
        return s.split("：", 1)[1]
    return s


def main():
    log.info("=== 道路交通量 整形 ===")
    g = gpd.read_parquet(SRC)
    g["_pref"] = pd.to_numeric(g["市区町村コード"], errors="coerce") // 1000
    sub = g[g["_pref"].isin(TARGET_PREF)].copy()
    log.info(f"  対象1都10県: {len(sub)}区間")

    name_hw = sub["路線名"].astype(str).str.contains("高速|自動車道", na=False)
    kind_hw = sub["道路種別"].astype(str).str.contains("高速", na=False)  # 高速自動車国道/都市高速
    exclusive = pd.to_numeric(sub["自動車専用道路の別"], errors="coerce") == 1
    t24num = pd.to_numeric(sub[C_T24], errors="coerce")
    keep = (~name_hw) & (~kind_hw) & (~exclusive) & (t24num > 0)
    sub = sub[keep].copy()
    log.info(f"  高速等除外・t24>0: {len(sub)}区間")

    # 同一基本区間(census)の重複行は t24 最大の1本に集約
    sub["_t24"] = pd.to_numeric(sub[C_T24], errors="coerce")
    sub = (sub.sort_values("_t24", ascending=False)
              .drop_duplicates(subset="census", keep="first"))
    log.info(f"  census重複集約後: {len(sub)}区間")

    rows = []
    for _, r in sub.iterrows():
        t24 = _num(r[C_T24]); t12 = _num(r[C_T12])
        pt = str(r[C_PT_UP] or "").strip() or str(r[C_PT_DN] or "").strip()
        cong = _num(r[C_CONG]); sw = _num(r[C_SIDEWALK]); lanes = _num(r[C_LANES])
        rec = {
            "road": str(r["路線名"] or "").strip(),
            "t24": int(t24) if t24 is not None else None,
            "t12": int(t12) if t12 is not None else None,
            "pt": pt,
            "cong": round(cong, 2) if cong is not None else None,
            "sidewalk": round(sw, 1) if sw is not None else None,
            "roadside": _strip_code(r[C_ROADSIDE]),
            "lanes": int(lanes) if lanes is not None else None,
        }
        # 空・None のプロパティは省いてファイルサイズを削減
        rows.append({k: v for k, v in rec.items() if v not in (None, "")})

    out = gpd.GeoDataFrame(rows, geometry=sub.geometry.values, crs=sub.crs)
    out = out.to_crs(epsg=4326)
    out["geometry"] = out.geometry.simplify(SIMPLIFY_TOL, preserve_topology=False)
    out = out[~out.geometry.is_empty & out.geometry.notna()]

    OUT.write_text(out.to_json(drop_id=True, ensure_ascii=False), encoding="utf-8")
    # 座標を5桁に丸めてサイズ削減（再読込→再書出し）
    data = json.loads(OUT.read_text(encoding="utf-8"))

    def round_coords(c):
        if isinstance(c, (int, float)):
            return round(c, COORD_DECIMALS)
        return [round_coords(x) for x in c]
    for feat in data["features"]:
        geom = feat.get("geometry")
        if geom and "coordinates" in geom:
            geom["coordinates"] = round_coords(geom["coordinates"])
            # 単一パートの MultiLineString は LineString に変換（ブラケット削減）
            if geom.get("type") == "MultiLineString" and len(geom["coordinates"]) == 1:
                geom["type"] = "LineString"
                geom["coordinates"] = geom["coordinates"][0]
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    kb = OUT.stat().st_size // 1024
    log.info(f"  保存: {OUT.name} ({len(data['features'])}本, {kb}KB)")
    # 参考: t24分布
    import numpy as np
    vals = np.array([f["properties"]["t24"] for f in data["features"] if f["properties"]["t24"]])
    log.info(f"  t24 中央値{int(np.median(vals))} / 90%{int(np.quantile(vals,.9))} / 最大{int(vals.max())}")
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
