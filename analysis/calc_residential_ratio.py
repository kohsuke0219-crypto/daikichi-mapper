"""
ステップ10-3: 住宅地比率の市区町村別集計

land_use_compact.csv の 100mメッシュ centroid を
市区町村ポリゴン（ward_population.geojson）に空間結合し、
各市区町村の建物用地比率（住宅地比率の代理）を算出する。

出力: analysis/residential_ratio.csv
  code          … 市区町村コード (5桁)
  city          … 市区町村名
  total_cells   … 市区町村内メッシュ総数
  building_cells … 建物用地 (0500) セル数
  residential_ratio … 建物用地比率 (0~1)
"""
import logging
from pathlib import Path
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

# ---------------------------------------------------------------------------
# ロギング
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
LOG_PATH = BASE_DIR / "progress.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# パス
# ---------------------------------------------------------------------------
LAND_USE_CSV   = BASE_DIR / "land_use_compact.csv"
WARD_GEOJSON   = BASE_DIR.parent / "docs" / "data" / "ward_population.geojson"
OUT_CSV        = BASE_DIR / "residential_ratio.csv"

# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main():
    log.info("=== ステップ10-3: 住宅地比率 集計 開始 ===")

    # ---- 1. 市区町村ポリゴン読み込み ----
    log.info("[1] 市区町村ポリゴン読み込み")
    wards = gpd.read_file(WARD_GEOJSON)
    wards = wards[["code", "city", "geometry"]].copy()
    log.info(f"  市区町村数: {len(wards)}")

    # ---- 2. 土地利用 CSV 読み込み（450万行）----
    log.info("[2] 土地利用 CSV 読み込み（450万行）")
    lu = pd.read_csv(LAND_USE_CSV, dtype={"land_use_code": str})
    log.info(f"  メッシュ数: {len(lu):,}")

    # ---- 3. Point GeoDataFrame に変換 ----
    log.info("[3] centroid を Point に変換")
    geometry = gpd.points_from_xy(lu["lon"], lu["lat"])
    lu_gdf = gpd.GeoDataFrame(lu[["mesh_code", "land_use_code"]], geometry=geometry, crs="EPSG:4326")

    # ---- 4. 空間結合（point in polygon）----
    log.info("[4] 空間結合（市区町村ポリゴンと結合）")
    # sjoin で各 point が属する市区町村を特定
    joined = gpd.sjoin(lu_gdf, wards[["code", "city", "geometry"]],
                       how="left", predicate="within")
    log.info(f"  結合完了: マッチ {joined['code'].notna().sum():,} / {len(joined):,}")

    # ---- 5. 市区町村ごとに集計 ----
    log.info("[5] 市区町村ごとに集計")
    joined_valid = joined[joined["code"].notna()].copy()

    total_counts = joined_valid.groupby("code").size().rename("total_cells")
    building_counts = (
        joined_valid[joined_valid["land_use_code"] == "0500"]
        .groupby("code").size().rename("building_cells")
    )

    ratio_df = pd.concat([total_counts, building_counts], axis=1).fillna(0)
    ratio_df["building_cells"] = ratio_df["building_cells"].astype(int)
    ratio_df["residential_ratio"] = ratio_df["building_cells"] / ratio_df["total_cells"]

    # city 名を付与
    code_to_city = wards.set_index("code")["city"].to_dict()
    ratio_df["city"] = ratio_df.index.map(code_to_city)
    ratio_df = ratio_df.reset_index().rename(columns={"code": "code"})
    ratio_df = ratio_df[["code", "city", "total_cells", "building_cells", "residential_ratio"]]
    ratio_df = ratio_df.sort_values("residential_ratio", ascending=False)

    # ---- 6. 保存 ----
    ratio_df.to_csv(OUT_CSV, index=False)
    log.info(f"  保存: {OUT_CSV.name} ({len(ratio_df)} 市区町村)")
    log.info(f"  住宅地比率 上位5:")
    for _, row in ratio_df.head(5).iterrows():
        log.info(f"    {row['city']} {row['code']}: {row['residential_ratio']:.3f} "
                 f"({row['building_cells']:,}/{row['total_cells']:,})")
    log.info(f"  住宅地比率 下位5:")
    for _, row in ratio_df.tail(5).iterrows():
        log.info(f"    {row['city']} {row['code']}: {row['residential_ratio']:.3f} "
                 f"({row['building_cells']:,}/{row['total_cells']:,})")

    log.info("=== 住宅地比率 集計 完了 ===")


if __name__ == "__main__":
    main()
