"""
サブステップ12-9: 最終スコア v4 計算

基本スコア   = (40歳以上女性人口 × 住宅地比率) ÷ 商圏面積(π r²)
立地ボーナス = 駅近(都心) or 道路近(郊外)  ※ station_bonus × road_bonus
競合ペナルティ = max(0.3, 1.0 - 商圏半径内競合数 × 0.15)
最終スコアv4  = 基本 × 立地 × 競合ペナルティ × 分断補正 × 県境ボーナス

人口は修正版(ward_pop_fixed.csv)を使用。

出力:
  analysis/score_v4.csv
  docs/data/score_v4_data.json （地図用・軽量）
"""
import json
import logging
import math
from pathlib import Path

import pandas as pd
import geopandas as gpd

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
CLASSIFIED   = BASE_DIR / "area_classified.csv"
STATION_PROX = BASE_DIR / "station_proximity.csv"
ROAD_PROX    = BASE_DIR / "road_proximity.csv"
SCORE_V2     = BASE_DIR / "score_v2.csv"
SCORE_V3     = BASE_DIR / "score_v3.csv"
COMP_JSON    = DOCS_DATA / "competitors_all.json"
WARD_POP     = BASE_DIR / "ward_pop_fixed.csv"

OUT_CSV      = BASE_DIR / "score_v4.csv"
OUT_JSON     = DOCS_DATA / "score_v4_data.json"
METRIC_CRS   = "EPSG:6677"


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def main():
    log.info("=== 12-9: スコアv4 計算 ===")

    # ---- 各データ読み込み ----
    log.info("[1] データ読み込み")
    cls   = pd.read_csv(CLASSIFIED, dtype={"code": str});  cls["code"]=cls["code"].str.zfill(5)
    stp   = pd.read_csv(STATION_PROX, dtype={"code": str}); stp["code"]=stp["code"].str.zfill(5)
    rdp   = pd.read_csv(ROAD_PROX, dtype={"code": str});    rdp["code"]=rdp["code"].str.zfill(5)
    v2    = pd.read_csv(SCORE_V2, dtype={"code": str});     v2["code"]=v2["code"].str.zfill(5)
    v3    = pd.read_csv(SCORE_V3, dtype={"code": str});     v3["code"]=v3["code"].str.zfill(5)
    wp    = pd.read_csv(WARD_POP, dtype={"code": str});     wp["code"]=wp["code"].str.zfill(5)

    # 統合ベース
    df = cls[["code","city","pref","total_pop","area_km2","pop_density",
              "station_density","area_type","trade_radius_km"]].copy()
    # 修正版 women_40plus
    df = df.merge(wp[["code","women_40plus"]], on="code", how="left")
    # residential_ratio, barrier_factor, border_bonus (人口非依存の係数)
    df = df.merge(v2[["code","residential_ratio","barrier_factor","border_bonus","score_norm"]],
                  on="code", how="left")
    df = df.rename(columns={"score_norm": "score_v2"})
    df = df.merge(v3[["code","score_v3"]], on="code", how="left")
    df = df.merge(stp[["code","nearest_station_m","station_bonus"]], on="code", how="left")
    df = df.merge(rdp[["code","nearest_road_m","road_bonus"]], on="code", how="left")

    # 欠損補完
    df["residential_ratio"] = df["residential_ratio"].fillna(df["residential_ratio"].median())
    df["barrier_factor"]    = df["barrier_factor"].fillna(1.0)
    df["border_bonus"]      = df["border_bonus"].fillna(1.0)
    df["station_bonus"]     = df["station_bonus"].fillna(1.0)
    df["road_bonus"]        = df["road_bonus"].fillna(1.0)
    df["women_40plus"]      = df["women_40plus"].fillna(0)

    # ---- 商圏内競合数 ----
    log.info("[2] 商圏内競合数カウント")
    wards = gpd.read_file(WARD_GEOJSON)[["code","geometry"]]
    wards["code"] = wards["code"].astype(str).str.zfill(5)
    wm = wards.to_crs(METRIC_CRS)
    wm["geometry"] = wm.geometry.centroid
    wm = wm.to_crs(epsg=4326)
    cent = {r["code"]: (r.geometry.y, r.geometry.x) for _, r in wm.iterrows()}

    with open(COMP_JSON, encoding="utf-8") as f:
        comps = [(float(c["latitude"]), float(c["longitude"]))
                 for c in json.load(f) if c.get("latitude") and c.get("longitude")]
    log.info(f"  競合 {len(comps)} 店")

    comp_counts = {}
    for code, (clat, clon) in cent.items():
        radius = df.loc[df["code"]==code, "trade_radius_km"]
        r = float(radius.iloc[0]) if len(radius) else 3.0
        n = sum(1 for (lat, lon) in comps if haversine_km(clat, clon, lat, lon) <= r)
        comp_counts[code] = n
    df["comp_in_radius"] = df["code"].map(comp_counts).fillna(0).astype(int)

    # ---- スコア計算 ----
    log.info("[3] スコアv4 計算")
    df["trade_area_km2"] = math.pi * df["trade_radius_km"]**2
    df["base_score"] = (df["women_40plus"] * df["residential_ratio"]) / df["trade_area_km2"]
    df["location_bonus"] = df["station_bonus"] * df["road_bonus"]
    df["comp_penalty"] = (1.0 - df["comp_in_radius"] * 0.15).clip(lower=0.3)

    df["score_v4_raw"] = (
        df["base_score"] *
        df["location_bonus"] *
        df["comp_penalty"] *
        df["barrier_factor"] *
        df["border_bonus"]
    )
    # 正規化 0-100
    lo, hi = df["score_v4_raw"].min(), df["score_v4_raw"].max()
    df["score_v4"] = ((df["score_v4_raw"] - lo) / (hi - lo) * 100).round(1)

    df["rank_v3"] = df["score_v3"].rank(ascending=False, method="min")
    df["rank_v4"] = df["score_v4"].rank(ascending=False, method="min")
    df["rank_chg"] = (df["rank_v3"] - df["rank_v4"]).fillna(0).astype(int)

    df = df.sort_values("score_v4", ascending=False)

    # ---- 保存 ----
    cols = ["code","city","pref","area_type","trade_radius_km",
            "total_pop","women_40plus","residential_ratio","pop_density","station_density",
            "nearest_station_m","nearest_road_m","station_bonus","road_bonus","location_bonus",
            "comp_in_radius","comp_penalty","barrier_factor","border_bonus",
            "base_score","score_v2","score_v3","score_v4","rank_v3","rank_v4","rank_chg"]
    df[cols].round(4).to_csv(OUT_CSV, index=False)
    log.info(f"  保存: {OUT_CSV.name} ({len(df)}行)")

    # 軽量JSON（地図用）
    data = {}
    for _, r in df.iterrows():
        data[r["code"]] = {
            "v4": round(float(r["score_v4"]),1),
            "v3": round(float(r["score_v3"]),1) if pd.notna(r["score_v3"]) else None,
            "v2": round(float(r["score_v2"]),1) if pd.notna(r["score_v2"]) else None,
            "type": r["area_type"],
            "radius": float(r["trade_radius_km"]),
            "w40": int(r["women_40plus"]),
            "res": round(float(r["residential_ratio"]),2),
            "st_m": int(r["nearest_station_m"]) if pd.notna(r["nearest_station_m"]) else None,
            "rd_m": int(r["nearest_road_m"]) if pd.notna(r["nearest_road_m"]) else None,
            "comp": int(r["comp_in_radius"]),
        }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    log.info(f"  保存: {OUT_JSON.name} ({OUT_JSON.stat().st_size//1024}KB)")

    # サマリ
    log.info("=== スコアv4 TOP10 ===")
    for _, r in df.head(10).iterrows():
        log.info(f"  {r['city']}({r['area_type']}) v4={r['score_v4']:.1f} "
                 f"女40+={int(r['women_40plus']):,} 競合{int(r['comp_in_radius'])} "
                 f"立地×{r['location_bonus']:.2f}")

    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
