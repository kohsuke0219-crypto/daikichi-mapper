"""
ステップ10-2: 地理データ前処理

ZIPのShapefileを読み込み、フィルタリング・GeoJSON変換して docs/data/ に保存する。

出力:
  docs/data/parks.geojson      … 1ha以上の都市公園（P13）
  docs/data/rivers.geojson     … 一・二級河川（W05）
  docs/data/mountains.geojson  … 平均標高150m以上のメッシュ（G04a）
  analysis/land_use_compact.csv … 100mメッシュ土地利用（L03b、centroid+コードのみ）
"""
import logging
import sys
import zipfile
import io
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import mapping

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
# パス設定
# ---------------------------------------------------------------------------
GEO_DATA_DIR = BASE_DIR / "geo_data"
DOCS_DATA_DIR = BASE_DIR.parent / "docs" / "data"
DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)

PREF_CODES = {"東京都": "13", "神奈川県": "14", "埼玉県": "11", "千葉県": "12"}
KANTO_MESH_CODES = [
    "5238", "5239", "5240",
    "5338", "5339", "5340",
    "5438", "5439", "5440",
]

# ---------------------------------------------------------------------------
# 共通ユーティリティ
# ---------------------------------------------------------------------------

def read_shp_from_zip(zip_path: Path, shp_name: str) -> gpd.GeoDataFrame:
    """ZIPからShapefileを読み込む（文字列カラムの文字化けを修正）"""
    gdf = gpd.read_file(f"zip://{zip_path}!{shp_name}", encoding="cp932")
    return gdf


def simplify_and_save(gdf: gpd.GeoDataFrame, out_path: Path,
                      tolerance: float = 0.0001, keep_cols: list = None):
    """WGS84に変換・座標簡略化して GeoJSON 保存"""
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    elif gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)

    if keep_cols:
        gdf = gdf[keep_cols + ["geometry"]]

    gdf["geometry"] = gdf["geometry"].simplify(tolerance, preserve_topology=True)
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out_path, driver="GeoJSON")
    log.info(f"  保存: {out_path.name} ({out_path.stat().st_size // 1024} KB, {len(gdf)} features)")

# ---------------------------------------------------------------------------
# P13: 都市公園（1ha以上）
# ---------------------------------------------------------------------------

def preprocess_parks():
    log.info("[P13] 都市公園 前処理（フィルタ: 面積1ha以上）")
    gdfs = []
    for pref, code in PREF_CODES.items():
        zip_path = GEO_DATA_DIR / f"P13_{code}.zip"
        shp_name = f"P13-11_{code}.shp"
        gdf = read_shp_from_zip(zip_path, shp_name)
        # P13_008 = 公園区域面積 (m²)
        filtered = gdf[gdf["P13_008"] >= 10000].copy()
        filtered["area_m2"] = filtered["P13_008"]
        log.info(f"  [{pref}] 全{len(gdf)}件 → 1ha以上 {len(filtered)}件")
        gdfs.append(filtered[["area_m2", "geometry"]])

    merged = pd.concat(gdfs, ignore_index=True)
    merged = gpd.GeoDataFrame(merged, crs=gdfs[0].crs)
    simplify_and_save(merged, DOCS_DATA_DIR / "parks.geojson",
                      tolerance=0.0001, keep_cols=["area_m2"])


# ---------------------------------------------------------------------------
# W05: 河川（一・二級河川）
# ---------------------------------------------------------------------------

def preprocess_rivers():
    log.info("[W05] 河川 前処理（フィルタ: 一級河川 W05_003='1'、二級河川 '2'）")
    gdfs = []
    for pref, code in PREF_CODES.items():
        zip_path = GEO_DATA_DIR / f"W05_{code}.zip"
        # W05 ZIPに含まれるStreamファイル名を動的検出
        with zipfile.ZipFile(zip_path) as zf:
            stream_shp = next(
                n for n in zf.namelist()
                if "Stream" in n and n.lower().endswith(".shp")
            )
        gdf = read_shp_from_zip(zip_path, stream_shp)
        # W05_003: 河川種別 ('1'=一級, '2'=二級)
        filtered = gdf[gdf["W05_003"].isin(["1", "2"])].copy()
        filtered["river_class"] = filtered["W05_003"].astype(int)
        filtered["river_name"] = filtered["W05_004"]
        log.info(f"  [{pref}] 全{len(gdf)}件 → 一・二級河川 {len(filtered)}件")
        gdfs.append(filtered[["river_class", "river_name", "geometry"]])

    merged = pd.concat(gdfs, ignore_index=True)
    merged = gpd.GeoDataFrame(merged, crs=gdfs[0].crs)
    simplify_and_save(merged, DOCS_DATA_DIR / "rivers.geojson",
                      tolerance=0.00005, keep_cols=["river_class", "river_name"])


# ---------------------------------------------------------------------------
# G04a: 標高メッシュ（平均標高150m以上）
# ---------------------------------------------------------------------------

def preprocess_mountains():
    log.info("[G04a] 標高メッシュ 前処理（フィルタ: 平均標高150m以上）")
    gdfs = []
    for mesh in KANTO_MESH_CODES:
        zip_path = GEO_DATA_DIR / f"G04a_{mesh}.zip"
        with zipfile.ZipFile(zip_path) as zf:
            shp_name = next(n for n in zf.namelist() if n.endswith(".shp"))
        gdf = read_shp_from_zip(zip_path, shp_name)

        # G04a_004 = 平均標高 (文字列、'unknown'=水域)
        # G04a_002 = 最小標高、G04a_003 = 最大標高
        gdf["elev_mean"] = pd.to_numeric(gdf["G04a_004"], errors="coerce").fillna(0)
        filtered = gdf[gdf["elev_mean"] >= 150].copy()
        log.info(f"  [メッシュ {mesh}] 全{len(gdf)}件 → 150m以上 {len(filtered)}件")
        if len(filtered) > 0:
            gdfs.append(filtered[["elev_mean", "geometry"]])

    if not gdfs:
        log.warning("  標高150m以上のメッシュが見つかりません")
        return

    merged = pd.concat(gdfs, ignore_index=True)
    merged = gpd.GeoDataFrame(merged, crs=gdfs[0].crs)
    # 山地メッシュは大量になるため dissolve してポリゴンを結合する
    log.info(f"  dissolve前: {len(merged)}件")
    dissolved = merged.dissolve().reset_index(drop=True)
    dissolved["type"] = "mountain"
    simplify_and_save(dissolved, DOCS_DATA_DIR / "mountains.geojson",
                      tolerance=0.001, keep_cols=["type"])


# ---------------------------------------------------------------------------
# L03b: 土地利用細分メッシュ（コンパクトCSV）
# ---------------------------------------------------------------------------

def preprocess_land_use():
    log.info("[L03b] 土地利用メッシュ 前処理（centroid+コードをCSVに保存）")
    rows = []
    for mesh in KANTO_MESH_CODES:
        zip_path = GEO_DATA_DIR / f"L03b_{mesh}.zip"
        with zipfile.ZipFile(zip_path) as zf:
            shp_name = next(n for n in zf.namelist() if n.endswith(".shp"))
        gdf = read_shp_from_zip(zip_path, shp_name)

        # L03b列名は環境によって文字化けするため位置でアクセス
        # 列構成: [メッシュコード, 土地利用コード, 撮影日, geometry]
        non_geom = [c for c in gdf.columns if c != "geometry"]
        if len(non_geom) < 2:
            log.warning(f"  [{mesh}] 列数不足: {non_geom}")
            continue

        mesh_col = non_geom[0]   # メッシュコード
        code_col = non_geom[1]   # 土地利用区分コード

        # 土地利用コードが '0500'（建物用地）の行のみ対象
        # （全コードを保持すると5.7M行×9メッシュで過大になるため）
        # → 住宅地比率 = 0500件数 / 全件数
        total_count = len(gdf)
        code_counts = gdf[code_col].value_counts().to_dict()

        # centroid 座標を算出
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)
        elif gdf.crs is None:
            gdf = gdf.set_crs(epsg=4326)

        gdf["lon"] = gdf.geometry.centroid.x
        gdf["lat"] = gdf.geometry.centroid.y

        chunk = gdf[[mesh_col, code_col, "lon", "lat"]].copy()
        chunk.columns = ["mesh_code", "land_use_code", "lon", "lat"]
        rows.append(chunk)

        building_cnt = code_counts.get("0500", 0)
        log.info(
            f"  [メッシュ {mesh}] 全{total_count}件 "
            f"建物用地(0500): {building_cnt}件 "
            f"({100*building_cnt/total_count:.1f}%)"
        )

    df = pd.concat(rows, ignore_index=True)
    out_path = BASE_DIR / "land_use_compact.csv"
    df.to_csv(out_path, index=False)
    log.info(f"  保存: {out_path.name} ({out_path.stat().st_size // 1024} KB, {len(df)}行)")


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

def main():
    import sys
    steps = sys.argv[1:]  # 例: python preprocess_geo.py parks rivers mountains landuse

    all_steps = ["parks", "rivers", "mountains", "landuse"]
    if not steps:
        steps = all_steps

    log.info(f"=== ステップ10-2 前処理 開始: {steps} ===")

    if "parks" in steps:
        preprocess_parks()

    if "rivers" in steps:
        preprocess_rivers()

    if "mountains" in steps:
        preprocess_mountains()

    if "landuse" in steps:
        preprocess_land_use()

    log.info("=== 前処理 完了 ===")


if __name__ == "__main__":
    main()
