"""
サブステップ12-5 & 12-6: エリアタイプ4分類 + 商圏半径付与

分類ロジック（人口密度＋駅密度）:
  超都心      : 人口密度8000+/km² かつ 駅密度0.3+/km² → 商圏半径1km
  都心住宅    : 人口密度5000+/km² かつ 駅密度0.1+/km² → 商圏半径2km
  郊外住宅    : 人口密度2000+/km²                      → 商圏半径3km
  ロードサイド: 上記以外                                → 商圏半径5km

出力: analysis/area_classified.csv
  code, city, pref, total_pop, area_km2, pop_density, station_density,
  area_type, trade_radius_km
"""
import logging
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).parent
LOG_PATH = BASE_DIR / "progress.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

METRICS_CSV = BASE_DIR / "area_metrics.csv"
OUT_CSV     = BASE_DIR / "area_classified.csv"

# 商圏半径(km)
TRADE_RADIUS = {
    "超都心":      1.0,
    "都心住宅":    2.0,
    "郊外住宅":    3.0,
    "ロードサイド": 5.0,
}


def classify(pop_density: float, station_density: float) -> str:
    if pop_density >= 8000 and station_density >= 0.3:
        return "超都心"
    if pop_density >= 5000 and station_density >= 0.1:
        return "都心住宅"
    if pop_density >= 2000:
        return "郊外住宅"
    return "ロードサイド"


def main():
    log.info("=== 12-5 & 12-6: エリアタイプ分類 + 商圏半径 ===")

    df = pd.read_csv(METRICS_CSV, dtype={"code": str})
    df["code"] = df["code"].str.zfill(5)

    df["area_type"] = df.apply(
        lambda r: classify(r["pop_density"], r["station_density"]), axis=1
    )
    df["trade_radius_km"] = df["area_type"].map(TRADE_RADIUS)

    # 並び順: タイプ → 人口密度降順
    type_order = {"超都心": 0, "都心住宅": 1, "郊外住宅": 2, "ロードサイド": 3}
    df["_ord"] = df["area_type"].map(type_order)
    df = df.sort_values(["_ord", "pop_density"], ascending=[True, False]).drop(columns="_ord")

    df.to_csv(OUT_CSV, index=False)
    log.info(f"  保存: {OUT_CSV.name} ({len(df)}行)")

    # 分布
    log.info("=== エリアタイプ分布 ===")
    counts = df["area_type"].value_counts()
    for t in ["超都心", "都心住宅", "郊外住宅", "ロードサイド"]:
        n = int(counts.get(t, 0))
        log.info(f"  {t}: {n} 市区町村 (商圏半径{TRADE_RADIUS[t]}km)")

    # 各タイプのサンプル
    for t in ["超都心", "都心住宅", "郊外住宅", "ロードサイド"]:
        sub = df[df["area_type"] == t].head(5)
        names = "、".join(f"{r['city']}({r['pop_density']:.0f})" for _, r in sub.iterrows())
        log.info(f"  [{t}] 例: {names}")

    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
