"""
サブステップ12-4: 人口密度・駅密度の計算

各市区町村について:
  面積(km²)   = ポリゴン面積（メートル投影 EPSG:6677 で計算）
  人口密度    = 総人口 ÷ 面積
  駅密度      = 市区町村内の駅数 ÷ 面積

出力: analysis/area_metrics.csv
  code, city, pref, total_pop, area_km2, pop_density, n_stations, station_density
"""
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

BASE_DIR  = Path(__file__).parent
DOCS_DATA = BASE_DIR.parent / "docs" / "data"
LOG_PATH  = BASE_DIR / "progress.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

WARD_GEOJSON = DOCS_DATA / "ward_population.geojson"
STATIONS     = DOCS_DATA / "rail_stations.geojson"
OUT_CSV      = BASE_DIR / "area_metrics.csv"

# 平面直角座標系 第IX系（関東向け、メートル単位）
METRIC_CRS = "EPSG:6677"


def main():
    log.info("=== 12-4: 人口密度・駅密度の計算 ===")

    # ---- 市区町村ポリゴン ----
    log.info("[1] 市区町村ポリゴン読み込み")
    wards = gpd.read_file(WARD_GEOJSON)
    wards["code"] = wards["code"].astype(str).str.zfill(5)
    log.info(f"  {len(wards)} 市区町村")

    # ---- 面積計算（メートル投影）----
    log.info("[2] 面積計算 (EPSG:6677)")
    wards_m = wards.to_crs(METRIC_CRS)
    wards["area_km2"] = wards_m.geometry.area / 1_000_000  # m² → km²

    # ---- 駅を空間結合してカウント ----
    log.info("[3] 駅の空間結合")
    stations = gpd.read_file(STATIONS)
    if stations.crs is None:
        stations = stations.set_crs(epsg=4326)
    stations = stations.to_crs(wards.crs)

    joined = gpd.sjoin(stations, wards[["code", "geometry"]],
                       how="inner", predicate="within")
    station_counts = joined.groupby("code").size().rename("n_stations")
    log.info(f"  結合: {len(joined)} / {len(stations)} 駅が市区町村にマッチ")

    # ---- メトリクス統合 ----
    log.info("[4] メトリクス算出")
    df = wards[["code", "city", "pref", "total_pop", "area_km2"]].copy()
    df = df.merge(station_counts, on="code", how="left")
    df["n_stations"] = df["n_stations"].fillna(0).astype(int)
    df["pop_density"]     = df["total_pop"] / df["area_km2"]
    df["station_density"] = df["n_stations"] / df["area_km2"]

    df = df.sort_values("pop_density", ascending=False)
    df.to_csv(OUT_CSV, index=False)
    log.info(f"  保存: {OUT_CSV.name} ({len(df)} 行)")

    # ---- サマリ ----
    log.info("=== 人口密度 上位5 ===")
    for _, r in df.head(5).iterrows():
        log.info(f"  {r['city']}({r['pref']}): "
                 f"人口密度={r['pop_density']:.0f}/km² "
                 f"駅密度={r['station_density']:.3f}/km² "
                 f"面積={r['area_km2']:.1f}km² 駅{r['n_stations']}")
    log.info("=== 人口密度 下位5 ===")
    for _, r in df.tail(5).iterrows():
        log.info(f"  {r['city']}({r['pref']}): "
                 f"人口密度={r['pop_density']:.0f}/km² "
                 f"面積={r['area_km2']:.1f}km²")

    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
