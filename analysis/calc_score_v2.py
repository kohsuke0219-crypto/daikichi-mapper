"""
ステップ10-5: 改良版出店スコア計算

スコア式:
  実効人口   = women_40plus × residential_ratio
  住宅地ボーナス = 1.0 + (residential_ratio - 0.3) × 0.5
  県境ボーナス   = 1.1（最寄り店舗が異なる都府県の場合）
  最終スコア    = 実効人口 × eff_dist_km × 住宅地ボーナス × 県境ボーナス

  ※ スコアが高い = 「人口が多く・住宅密集しており・近い競合店がない」市区町村
     → 出店機会が大きいと解釈

出力:
  analysis/score_v2.csv
  docs/data/score_v2.geojson  （地図描画用）
"""
import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

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
DOCS_DATA      = BASE_DIR.parent / "docs" / "data"
WARD_GEOJSON   = DOCS_DATA / "ward_population.geojson"
RATIO_CSV      = BASE_DIR / "residential_ratio.csv"
DIST_CSV       = BASE_DIR / "effective_distance.csv"
OUT_CSV        = BASE_DIR / "score_v2.csv"
OUT_GEOJSON    = DOCS_DATA / "score_v2.geojson"

# 都府県コードプレフィックス
PREF_PREFIX = {"東京都": "13", "神奈川県": "14", "埼玉県": "11", "千葉県": "12"}

# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main():
    log.info("=== ステップ10-5: 改良版スコア計算 開始 ===")

    # ---- 1. データ読み込み ----
    log.info("[1] データ読み込み")
    wards = gpd.read_file(WARD_GEOJSON)
    ratio_df = pd.read_csv(RATIO_CSV, dtype={"code": str})
    dist_df  = pd.read_csv(DIST_CSV,  dtype={"code": str})
    log.info(f"  市区町村: {len(wards)}, 住宅地比率: {len(ratio_df)}, 実効距離: {len(dist_df)}")

    # ---- 2. データ結合 ----
    log.info("[2] データ結合")
    wards["code"] = wards["code"].astype(str).str.zfill(5)
    merged = wards.merge(ratio_df[["code", "residential_ratio"]], on="code", how="left")
    merged = merged.merge(dist_df[["code", "nearest_store", "store_pref",
                                    "raw_dist_km", "barrier_factor", "eff_dist_km",
                                    "has_park_cross", "has_river_cross", "has_mtn_cross"]],
                          on="code", how="left")

    # 住宅地比率が不明な市区町村にはデフォルト値（全体中央値）を適用
    median_ratio = ratio_df["residential_ratio"].median()
    missing = merged["residential_ratio"].isna().sum()
    merged["residential_ratio"] = merged["residential_ratio"].fillna(median_ratio)
    log.info(f"  住宅地比率 不明 → 中央値({median_ratio:.3f})で補完: {missing} 市区町村")

    # ---- 3. スコア計算 ----
    log.info("[3] スコア計算")

    # 実効人口
    merged["effective_pop"] = merged["women_40plus"] * merged["residential_ratio"]

    # 住宅地ボーナス (ratio=0.3 で 1.0、ratio=0.7 で 1.2、ratio=0.1 で 0.9)
    merged["housing_bonus"] = 1.0 + (merged["residential_ratio"] - 0.3) * 0.5
    merged["housing_bonus"] = merged["housing_bonus"].clip(lower=0.7, upper=1.5)

    # 県境ボーナス (市区町村の都道府県と最寄り店舗の都道府県が異なる場合 ×1.1)
    def pref_code_from_city_code(city_code: str) -> str:
        return str(city_code)[:2] if city_code else ""

    merged["ward_pref_code"] = merged["code"].apply(pref_code_from_city_code)
    pref_code_map = {v: k for k, v in PREF_PREFIX.items()}
    merged["ward_pref"] = merged["ward_pref_code"].map(pref_code_map)

    def calc_border_bonus(row):
        if pd.isna(row["store_pref"]) or pd.isna(row["ward_pref"]):
            return 1.0
        return 1.1 if row["store_pref"] != row["ward_pref"] else 1.0

    merged["border_bonus"] = merged.apply(calc_border_bonus, axis=1)

    # 最終スコア（高いほど出店機会が大きい）
    # eff_dist_km を distance factor として使う（遠いほどスコア高）
    # ただし距離0に近い場合（既存店舗と同じ場所）はフロアを設定
    merged["eff_dist_km"] = merged["eff_dist_km"].fillna(merged["raw_dist_km"])
    merged["eff_dist_capped"] = merged["eff_dist_km"].clip(lower=0.5)

    merged["score_v2"] = (
        merged["effective_pop"] *
        merged["eff_dist_capped"] *
        merged["housing_bonus"] *
        merged["border_bonus"]
    )

    # ---- 4. 正規化スコア (0–100) ----
    s_min, s_max = merged["score_v2"].min(), merged["score_v2"].max()
    merged["score_norm"] = ((merged["score_v2"] - s_min) / (s_max - s_min) * 100).round(1)

    # 従来スコア（women_40plus × raw_dist のみ）との比較用
    merged["score_v1"] = merged["women_40plus"] * merged["raw_dist_km"].fillna(0)

    # ---- 5. CSV 保存 ----
    cols_csv = [
        "code", "pref", "city",
        "total_pop", "women_40plus",
        "residential_ratio", "effective_pop",
        "raw_dist_km", "barrier_factor", "eff_dist_km",
        "has_park_cross", "has_river_cross", "has_mtn_cross",
        "housing_bonus", "border_bonus",
        "score_v2", "score_norm", "score_v1",
        "nearest_store", "store_pref",
    ]
    out = merged[cols_csv].sort_values("score_norm", ascending=False).round(4)
    out.to_csv(OUT_CSV, index=False)
    log.info(f"  CSV保存: {OUT_CSV.name} ({len(out)} 件)")

    # ---- 6. GeoJSON 保存（地図表示用） ----
    geo_cols = [
        "code", "city", "pref",
        "women_40plus", "residential_ratio", "effective_pop",
        "raw_dist_km", "eff_dist_km", "barrier_factor",
        "housing_bonus", "score_v2", "score_norm", "score_v1",
        "nearest_store", "geometry",
    ]
    geo_out = merged[geo_cols].copy()
    geo_out = geo_out[~geo_out.geometry.is_empty & geo_out.geometry.notna()]
    geo_out.to_file(OUT_GEOJSON, driver="GeoJSON")
    log.info(f"  GeoJSON保存: {OUT_GEOJSON.name} ({OUT_GEOJSON.stat().st_size // 1024} KB, {len(geo_out)} features)")

    # ---- 7. サマリ表示 ----
    log.info("=== 改良版スコア TOP 10 ===")
    top10 = out.head(10)
    for _, row in top10.iterrows():
        log.info(
            f"  {row['city']}({row['pref']}) "
            f"score={row['score_norm']:.1f} "
            f"pop40+={int(row['women_40plus']):,} "
            f"res_ratio={row['residential_ratio']:.2f} "
            f"eff_dist={row['eff_dist_km']:.1f}km"
        )

    log.info("=== スコア計算 完了 ===")


if __name__ == "__main__":
    main()
