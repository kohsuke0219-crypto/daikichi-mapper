"""
サブステップ12-8: 幹線道路近接スコア（郊外エリア用）

各市区町村重心から最寄り幹線道路（国道）までの距離を計算。
郊外住宅・ロードサイドエリアのみ立地ボーナスを適用:
  500m以内 → ×1.3 / 1km以内 → ×1.15 / それ以上 → ×0.85（車集客困難）

出力: analysis/road_proximity.csv
  code, city, area_type, nearest_road_m, road_bonus
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
# 近接計算には trunk+primary を含む生データを使用（スペック「国道・主要地方道」）。
# 表示用 major_roads.geojson は trunk のみだが、距離計算は全幹線で行う。
ROADS_RAW    = BASE_DIR / "geo_data" / "roads_kanto.geojson"
ROADS_DISP   = DOCS_DATA / "major_roads.geojson"
ROADS        = ROADS_RAW if ROADS_RAW.exists() else ROADS_DISP
CLASSIFIED   = BASE_DIR / "area_classified.csv"
OUT_CSV      = BASE_DIR / "road_proximity.csv"
METRIC_CRS   = "EPSG:6677"

SUBURBAN_TYPES = {"郊外住宅", "ロードサイド"}


def road_bonus(dist_m: float, area_type: str) -> float:
    """郊外エリアのみ幹線道路近接ボーナス。それ以外は1.0(中立)"""
    if area_type not in SUBURBAN_TYPES:
        return 1.0
    if dist_m <= 500:
        return 1.3
    if dist_m <= 1000:
        return 1.15
    return 0.85  # 幹線から遠い郊外は車集客困難


def main():
    log.info("=== 12-8: 幹線道路近接スコア ===")

    wards = gpd.read_file(WARD_GEOJSON)[["code", "city", "geometry"]]
    wards["code"] = wards["code"].astype(str).str.zfill(5)
    roads = gpd.read_file(ROADS)
    if roads.crs is None:
        roads = roads.set_crs(epsg=4326)

    wards_m = wards.to_crs(METRIC_CRS)
    roads_m = roads.to_crs(METRIC_CRS)
    wards_m["geometry"] = wards_m.geometry.centroid

    log.info("[1] 最寄り道路距離 (sjoin_nearest)")
    nearest = gpd.sjoin_nearest(wards_m, roads_m[["geometry"]],
                                how="left", distance_col="dist_m")
    nearest = nearest.drop_duplicates(subset="code")
    log.info(f"  {len(nearest)} 市区町村")

    cls = pd.read_csv(CLASSIFIED, dtype={"code": str})
    cls["code"] = cls["code"].str.zfill(5)
    df = nearest[["code", "city", "dist_m"]].merge(
        cls[["code", "area_type"]], on="code", how="left"
    )
    df["nearest_road_m"] = df["dist_m"].round(0)
    df["road_bonus"] = df.apply(
        lambda r: road_bonus(r["dist_m"], r["area_type"]), axis=1
    )
    df = df[["code", "city", "area_type", "nearest_road_m", "road_bonus"]]
    df.to_csv(OUT_CSV, index=False)
    log.info(f"  保存: {OUT_CSV.name} ({len(df)}行)")

    suburban = df[df["area_type"].isin(SUBURBAN_TYPES)]
    log.info(f"=== 郊外エリア({len(suburban)}) 道路ボーナス分布 ===")
    log.info(f"  {suburban['road_bonus'].value_counts().to_dict()}")
    log.info(f"  最寄り道路 中央値: {suburban['nearest_road_m'].median():.0f}m")

    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
