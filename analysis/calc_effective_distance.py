"""
ステップ10-4: 分断要素を考慮した実効距離計算

各市区町村重心 × 全店舗 の haversine 距離を計算し、
直線上の分断要素（公園・河川・山地）を検出して補正係数を掛ける。

補正係数:
  公園 (1ha+) との交差 → ×1.2
  河川 (一・二級) との交差 → ×1.3
  山地 (標高150m+) との交差 → ×1.5
  複数該当は乗算

各市区町村について「最も近い店舗への実効距離」を算出して保存。

出力: analysis/effective_distance.csv
  code             … 市区町村コード
  city             … 市区町村名
  nearest_store    … 最寄り店舗名
  store_pref       … 最寄り店舗都道府県
  raw_dist_km      … haversine 距離 (km)
  barrier_factor   … 分断補正係数
  eff_dist_km      … 実効距離 (km)
  has_park_cross   … 公園交差フラグ
  has_river_cross  … 河川交差フラグ
  has_mtn_cross    … 山地交差フラグ
"""
import logging
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

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
DOCS_DATA = BASE_DIR.parent / "docs" / "data"
WARD_GEOJSON   = DOCS_DATA / "ward_population.geojson"
STORES_JSON    = DOCS_DATA / "stores.json"
PARKS_GEOJSON  = DOCS_DATA / "parks.geojson"
RIVERS_GEOJSON = DOCS_DATA / "rivers.geojson"
MOUNTS_GEOJSON = DOCS_DATA / "mountains.geojson"
OUT_CSV        = BASE_DIR / "effective_distance.csv"

# 分断補正係数
PARK_FACTOR  = 1.2
RIVER_FACTOR = 1.3
MTN_FACTOR   = 1.5

# ---------------------------------------------------------------------------
# Haversine 距離 (km)
# ---------------------------------------------------------------------------

def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# 障害物ツリー構築
# ---------------------------------------------------------------------------

def build_tree(geojson_path: Path):
    """GeoJSON を読み込んで STRtree を構築"""
    gdf = gpd.read_file(geojson_path)
    geoms = list(gdf.geometry)
    tree = STRtree(geoms)
    return tree, geoms


def line_crosses_any(line: LineString, tree: STRtree, geoms: list) -> bool:
    """LineString が障害物ジオメトリのいずれかと交差するか"""
    candidates = tree.query(line)
    for idx in candidates:
        if line.intersects(geoms[idx]):
            return True
    return False


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main():
    log.info("=== ステップ10-4: 実効距離計算 開始 ===")

    # ---- 1. データ読み込み ----
    log.info("[1] データ読み込み")
    wards = gpd.read_file(WARD_GEOJSON)[["code", "city", "geometry"]]
    stores_df = pd.read_json(STORES_JSON)
    stores_df = stores_df[stores_df["lat"].notna() & stores_df["lng"].notna()]
    log.info(f"  市区町村: {len(wards)}, 店舗: {len(stores_df)}")

    # ---- 2. 市区町村重心 ----
    log.info("[2] 市区町村重心計算")
    # 重心計算は投影座標系が望ましいが、精度要件が低いため geographic CRS で続行
    wards["centroid"] = wards.geometry.centroid
    wards["c_lat"] = wards["centroid"].y
    wards["c_lon"] = wards["centroid"].x

    # ---- 3. 障害物ツリー ----
    log.info("[3] 障害物ツリー構築")
    park_tree,  park_geoms  = build_tree(PARKS_GEOJSON)
    river_tree, river_geoms = build_tree(RIVERS_GEOJSON)
    mtn_tree,   mtn_geoms   = build_tree(MOUNTS_GEOJSON)
    log.info(f"  公園: {len(park_geoms)}, 河川: {len(river_geoms)}, 山地: {len(mtn_geoms)}")

    # ---- 4. 市区町村 × 店舗 で最寄り実効距離計算 ----
    log.info(f"[4] 距離計算 ({len(wards)} × {len(stores_df)} = {len(wards)*len(stores_df):,} 組合せ)")

    store_records = stores_df.to_dict("records")
    results = []

    for wi, ward in wards.iterrows():
        c_lat, c_lon = ward["c_lat"], ward["c_lon"]
        best = None

        for s in store_records:
            s_lat, s_lng = s["lat"], s["lng"]
            raw_dist = haversine(c_lat, c_lon, s_lat, s_lng)

            line = LineString([(c_lon, c_lat), (s_lng, s_lat)])

            has_park  = line_crosses_any(line, park_tree,  park_geoms)
            has_river = line_crosses_any(line, river_tree, river_geoms)
            has_mtn   = line_crosses_any(line, mtn_tree,   mtn_geoms)

            factor = (PARK_FACTOR  if has_park  else 1.0) * \
                     (RIVER_FACTOR if has_river else 1.0) * \
                     (MTN_FACTOR   if has_mtn   else 1.0)

            eff_dist = raw_dist * factor

            if best is None or eff_dist < best["eff_dist_km"]:
                best = {
                    "code": ward["code"],
                    "city": ward["city"],
                    "nearest_store": s["name"],
                    "store_pref": s.get("prefecture", ""),
                    "raw_dist_km": round(raw_dist, 4),
                    "barrier_factor": round(factor, 4),
                    "eff_dist_km": round(eff_dist, 4),
                    "has_park_cross":  int(has_park),
                    "has_river_cross": int(has_river),
                    "has_mtn_cross":   int(has_mtn),
                }

        if best:
            results.append(best)

        if (wi + 1) % 50 == 0:
            log.info(f"  進捗: {wi + 1}/{len(wards)}")

    # ---- 5. 保存 ----
    df = pd.DataFrame(results)
    df.to_csv(OUT_CSV, index=False)
    log.info(f"  保存: {OUT_CSV.name} ({len(df)} 件)")

    # サマリ
    n_park  = (df["has_park_cross"]  == 1).sum()
    n_river = (df["has_river_cross"] == 1).sum()
    n_mtn   = (df["has_mtn_cross"]   == 1).sum()
    log.info(f"  公園交差あり市区町村: {n_park}")
    log.info(f"  河川交差あり市区町村: {n_river}")
    log.info(f"  山地交差あり市区町村: {n_mtn}")
    log.info(f"  平均 raw_dist: {df['raw_dist_km'].mean():.2f} km")
    log.info(f"  平均 eff_dist: {df['eff_dist_km'].mean():.2f} km")

    log.info("=== 実効距離計算 完了 ===")


if __name__ == "__main__":
    main()
