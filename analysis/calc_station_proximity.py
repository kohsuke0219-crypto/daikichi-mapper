"""
サブステップ12-7: 駅近接スコア（都心エリア用）

各市区町村重心から最寄り駅までの距離を計算。
超都心・都心住宅エリアのみ立地ボーナスを適用:
  300m以内 → ×1.3 / 500m以内 → ×1.15 / それ以上 → ×1.0

出力: analysis/station_proximity.csv
  code, city, area_type, nearest_station_m, station_bonus
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

WARD_GEOJSON  = DOCS_DATA / "ward_population.geojson"
STATIONS      = DOCS_DATA / "rail_stations.geojson"
CLASSIFIED    = BASE_DIR / "area_classified.csv"
OUT_CSV       = BASE_DIR / "station_proximity.csv"
METRIC_CRS    = "EPSG:6677"

URBAN_TYPES = {"超都心", "都心住宅"}


def station_bonus(dist_m: float, area_type: str) -> float:
    """都心エリアのみ駅近ボーナス。それ以外は1.0(中立)"""
    if area_type not in URBAN_TYPES:
        return 1.0
    if dist_m <= 300:
        return 1.3
    if dist_m <= 500:
        return 1.15
    return 1.0


def main():
    log.info("=== 12-7: 駅近接スコア ===")

    wards = gpd.read_file(WARD_GEOJSON)[["code", "city", "geometry"]]
    wards["code"] = wards["code"].astype(str).str.zfill(5)
    stations = gpd.read_file(STATIONS)
    if stations.crs is None:
        stations = stations.set_crs(epsg=4326)

    # メートル投影
    wards_m = wards.to_crs(METRIC_CRS)
    stations_m = stations.to_crs(METRIC_CRS)

    # 重心
    wards_m["geometry"] = wards_m.geometry.centroid

    log.info("[1] 最寄り駅距離 (sjoin_nearest)")
    nearest = gpd.sjoin_nearest(wards_m, stations_m[["geometry"]],
                                how="left", distance_col="dist_m")
    # code重複（同距離複数マッチ）を除去
    nearest = nearest.drop_duplicates(subset="code")
    log.info(f"  {len(nearest)} 市区町村")

    # エリアタイプ結合
    cls = pd.read_csv(CLASSIFIED, dtype={"code": str})
    cls["code"] = cls["code"].str.zfill(5)
    df = nearest[["code", "city", "dist_m"]].merge(
        cls[["code", "area_type"]], on="code", how="left"
    )
    df["nearest_station_m"] = df["dist_m"].round(0)
    df["station_bonus"] = df.apply(
        lambda r: station_bonus(r["dist_m"], r["area_type"]), axis=1
    )
    df = df[["code", "city", "area_type", "nearest_station_m", "station_bonus"]]
    df.to_csv(OUT_CSV, index=False)
    log.info(f"  保存: {OUT_CSV.name} ({len(df)}行)")

    # サマリ（都心エリアのボーナス分布）
    urban = df[df["area_type"].isin(URBAN_TYPES)]
    log.info(f"=== 都心エリア({len(urban)}) 駅近ボーナス分布 ===")
    log.info(f"  {urban['station_bonus'].value_counts().to_dict()}")
    log.info(f"  最寄り駅 中央値: {urban['nearest_station_m'].median():.0f}m")

    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
