"""
ステップ11-7: 競合を加味した改良版スコア v3

スコアv2 をベースに競合密度ペナルティを追加:
  競合密度ペナルティ = max(0.3, 1.0 - 半径1km以内の競合店数 × 0.15)
  競合空白ボーナス  = 半径2km以内に競合店がゼロなら × 1.2
  最終スコアv3 = スコアv2 × 競合密度ペナルティ × 競合空白ボーナス

出力:
  analysis/score_v3.csv
  docs/data/score_v3_data.json  （地図用軽量JSON）
"""
import json
import logging
import math
from pathlib import Path

import pandas as pd
import geopandas as gpd

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
DOCS_DATA     = BASE_DIR.parent / "docs" / "data"
WARD_GEOJSON  = DOCS_DATA / "ward_population.geojson"
SCORE_V2_CSV  = BASE_DIR / "score_v2.csv"
COMP_JSON     = DOCS_DATA / "competitors_all.json"
OUT_CSV       = BASE_DIR / "score_v3.csv"
OUT_DATA_JSON = DOCS_DATA / "score_v3_data.json"

# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main():
    log.info("=== ステップ11-7: スコアv3 計算開始 ===")

    # ---- 1. データ読み込み ----
    log.info("[1] データ読み込み")
    score_v2 = pd.read_csv(SCORE_V2_CSV, dtype={"code": str})
    wards    = gpd.read_file(WARD_GEOJSON)[["code", "geometry"]]
    wards["code"] = wards["code"].astype(str).str.zfill(5)

    with open(COMP_JSON, encoding="utf-8") as f:
        competitors = json.load(f)

    comp_coords = [
        (float(c["latitude"]), float(c["longitude"]), c["brand"])
        for c in competitors
        if c.get("latitude") and c.get("longitude")
    ]
    log.info(f"  スコアv2: {len(score_v2)}件, 競合店: {len(comp_coords)}件")

    # ---- 2. 市区町村重心 ----
    log.info("[2] 市区町村重心計算")
    wards["centroid"] = wards.geometry.centroid
    wards["c_lat"]    = wards["centroid"].y
    wards["c_lon"]    = wards["centroid"].x

    score_v2 = score_v2.merge(
        wards[["code", "c_lat", "c_lon"]], on="code", how="left"
    )

    # ---- 3. 競合密度スコア計算 ----
    log.info("[3] 競合密度ペナルティ & 空白ボーナス計算")

    results = []
    for _, row in score_v2.iterrows():
        c_lat = row.get("c_lat")
        c_lon = row.get("c_lon")
        if pd.isna(c_lat) or pd.isna(c_lon):
            results.append({
                "code": row["code"],
                "comp_count_1km": 0,
                "comp_count_2km": 0,
                "comp_penalty":   1.0,
                "comp_bonus":     1.0,
            })
            continue

        count_1km = 0
        count_2km = 0
        for clat, clng, brand in comp_coords:
            d = haversine_km(c_lat, c_lon, clat, clng)
            if d <= 1.0:
                count_1km += 1
            if d <= 2.0:
                count_2km += 1

        penalty = max(0.3, 1.0 - count_1km * 0.15)
        bonus   = 1.2 if count_2km == 0 else 1.0

        results.append({
            "code": row["code"],
            "comp_count_1km": count_1km,
            "comp_count_2km": count_2km,
            "comp_penalty":   round(penalty, 3),
            "comp_bonus":     round(bonus, 2),
        })

    comp_df = pd.DataFrame(results)
    merged  = score_v2.merge(comp_df, on="code", how="left")

    # ---- 4. スコアv3 計算 ----
    log.info("[4] スコアv3 計算")
    merged["score_v3_raw"] = (
        merged["score_v2"] *
        merged["comp_penalty"] *
        merged["comp_bonus"]
    )

    # 正規化 (0-100)
    s_min = merged["score_v3_raw"].min()
    s_max = merged["score_v3_raw"].max()
    merged["score_v3"] = (
        (merged["score_v3_raw"] - s_min) / (s_max - s_min) * 100
    ).round(1)

    merged["rank_v2"] = merged["score_norm"].rank(ascending=False, method="min").astype(int)
    merged["rank_v3"] = merged["score_v3"].rank(ascending=False, method="min").astype(int)
    merged["rank_diff_v3"] = merged["rank_v2"] - merged["rank_v3"]

    # ---- 5. CSV 保存 ----
    cols_out = [
        "code", "pref", "city",
        "women_40plus", "residential_ratio", "eff_dist_km",
        "score_norm", "score_v3",
        "comp_count_1km", "comp_count_2km", "comp_penalty", "comp_bonus",
        "rank_v2", "rank_v3", "rank_diff_v3",
        "nearest_store",
    ]
    out = merged[cols_out].sort_values("score_v3", ascending=False).round(4)
    out.to_csv(OUT_CSV, index=False)
    log.info(f"  CSV: {OUT_CSV.name} ({len(out)}件)")

    # ---- 6. 軽量 JSON 保存（地図用）----
    data_json = {}
    for _, row in merged.iterrows():
        data_json[row["code"]] = {
            "v3":          round(float(row["score_v3"]), 1),
            "v2":          round(float(row["score_norm"]), 1),
            "comp1km":     int(row["comp_count_1km"]),
            "comp2km":     int(row["comp_count_2km"]),
            "penalty":     round(float(row["comp_penalty"]), 2),
        }
    with open(OUT_DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(data_json, f, ensure_ascii=False, separators=(",", ":"))
    log.info(f"  JSON: {OUT_DATA_JSON.name} ({OUT_DATA_JSON.stat().st_size // 1024}KB)")

    # ---- 7. サマリ ----
    log.info("=== TOP10 (v3) ===")
    for _, row in out.head(10).iterrows():
        log.info(
            f"  {row['city']}({row['pref']}) "
            f"v3={row['score_v3']:.1f} v2={row['score_norm']:.1f} "
            f"comp1km={row['comp_count_1km']} penalty={row['comp_penalty']:.2f}"
        )

    log.info("=== v2→v3 大幅DOWN (競合密集) TOP5 ===")
    down = merged.sort_values("rank_diff_v3").head(5)
    for _, row in down.iterrows():
        log.info(
            f"  {row['city']} v2rank={row['rank_v2']}→v3rank={row['rank_v3']} "
            f"comp1km={row['comp_count_1km']}"
        )

    log.info("=== v2→v3 大幅UP (競合空白) TOP5 ===")
    up = merged.sort_values("rank_diff_v3", ascending=False).head(5)
    for _, row in up.iterrows():
        log.info(
            f"  {row['city']} v2rank={row['rank_v2']}→v3rank={row['rank_v3']} "
            f"comp2km={row['comp_count_2km']} bonus={row['comp_bonus']:.1f}"
        )

    log.info("=== スコアv3 計算完了 ===")


if __name__ == "__main__":
    main()
