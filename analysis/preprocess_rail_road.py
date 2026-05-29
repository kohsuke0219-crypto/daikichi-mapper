"""
サブステップ12-3: 鉄道駅・道路データ前処理

駅: Point GeoJSON（そのまま使用可能）
道路: 簡略化（tolerance=0.001）してファイルサイズ削減

出力:
  docs/data/rail_stations.geojson  （軽量化済み）
  docs/data/major_roads.geojson    （簡略化済み・1MB以下目標）
"""
import json
import logging
from pathlib import Path
import geopandas as gpd

BASE_DIR  = Path(__file__).parent
GEO_DATA  = BASE_DIR / "geo_data"
DOCS_DATA = BASE_DIR.parent / "docs" / "data"
LOG_PATH  = BASE_DIR / "progress.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)


def process_stations():
    """駅データを docs/data に配置（軽量プロパティのみ）"""
    src = GEO_DATA / "stations_kanto.geojson"
    dst = DOCS_DATA / "rail_stations.geojson"

    gdf = gpd.read_file(src)
    log.info(f"  駅: {len(gdf)}件 入力 cols={list(gdf.columns)}")

    # 必要なプロパティだけ残す
    keep = [c for c in ["name", "operator", "geometry"] if c in gdf.columns]
    gdf = gdf[keep]

    # WGS84 確認
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    gdf.to_file(dst, driver="GeoJSON")
    kb = dst.stat().st_size // 1024
    log.info(f"  保存: {dst.name} ({kb}KB, {len(gdf)}駅)")


def process_roads():
    """道路データを簡略化して docs/data に配置"""
    src = GEO_DATA / "roads_kanto.geojson"
    dst = DOCS_DATA / "major_roads.geojson"

    gdf = gpd.read_file(src)
    log.info(f"  道路: {len(gdf)} way 入力 ({src.stat().st_size//1024}KB)")

    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    # 国道（trunk）のみに絞る（primary は除外してサイズ削減）
    if "highway" in gdf.columns:
        before = len(gdf)
        gdf = gdf[gdf["highway"] == "trunk"].copy()
        log.info(f"  trunk のみ: {before} → {len(gdf)} way")

    # ref（国道番号）で dissolve → セグメント数を大幅削減
    if "ref" in gdf.columns:
        # ref が空文字の行は "unnamed" に統一
        gdf["ref"] = gdf["ref"].fillna("").replace("", "unnamed")
        before = len(gdf)
        gdf = gdf.dissolve(by="ref", aggfunc="first").reset_index()
        log.info(f"  dissolve: {before} → {len(gdf)} (by ref)")

    # dissolve 後も頂点が多いので簡略化 (tolerance=0.002 ≒ 約200m)
    gdf["geometry"] = gdf["geometry"].simplify(0.002, preserve_topology=True)
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]

    # 必要プロパティだけ
    keep = [c for c in ["name", "ref", "highway", "geometry"] if c in gdf.columns]
    gdf = gdf[keep]

    gdf.to_file(dst, driver="GeoJSON")
    kb = dst.stat().st_size // 1024
    log.info(f"  保存: {dst.name} ({kb}KB, {len(gdf)} way)")


def main():
    log.info("=== 12-3: 前処理 ===")
    process_stations()
    process_roads()
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
