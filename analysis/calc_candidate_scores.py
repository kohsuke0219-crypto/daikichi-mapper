"""
出店候補地スコアリング（戦略①都内スーパー近郊 / 戦略②田舎ブルーオーシャン）

候補地点 = 生活動線レイヤー（スーパー・複合施設 #DB2777）。
各候補に周辺指標スコア(0-10)を付与し、2戦略の合成スコア(0-100)で上位10を抽出。

■ 需要の裏付け(戦略②)は4ソースの複合に一般化:
   (a)漁業就業者数 (b)製造業従業者数 (c)農業産出額 (d)商業従業者数
   各ソースを市区町村単位で0-10に正規化(percentile)し、複合 = max(a,b,c,d)
   + 複数ソースが高い地域はボーナス(+1〜2)。海なし/データ無しソースは0。
   → 漁業町・工業町・農業町・旧商家町を同じ土俵で評価。

データ出所(取得日2026-06-03):
  候補/競合/大吉/人口 = docs/data/*.json,*.geojson（既存パイプライン）
  需要の裏付け = e-Stat 社会人口統計体系 市区町村データ C経済基盤(0000020103)
                 → analysis/demand_backing.csv
  ロードサイド適性 = 幹線道路データが1都3県のみのため公平性優先で一律(TODO)

出力: docs/data/ranking_strategy1.json / ranking_strategy2.json
      （各上位10、スコア内訳・需要内訳・最寄り競合距離・推定商圏人口・近接スーパー名）
"""
import csv
import json
import logging
import math
from pathlib import Path

import numpy as np
import geopandas as gpd

BASE_DIR  = Path(__file__).parent
DOCS_DATA = BASE_DIR.parent / "docs" / "data"
LOG_PATH  = BASE_DIR / "progress.log"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# ============================================================
# 調整可能な定数（配点・重み・ソース）
# ============================================================
R_SUPER_KM       = 1.5      # スーパー近接を数える半径
R_COMP_KM        = 2.0      # 競合をカウントする半径
SUPER_CAP        = 8        # 近接スーパーがこの数で満点(10)
COMP_DIST_CAP_KM = 5.0      # 最寄り競合がこの距離で満点
POP_CAP          = 100000   # 女性40+がこの数で満点
CANNIBAL_CAP_KM  = 5.0      # 最寄り大吉がこの距離で満点
ROADSIDE_UNIFORM = 5.0      # TODO: 幹線道路データ全県整備後に置換
DEMAND_HIGH      = 7.0      # 需要ボーナス判定の閾値
POP_CUTOFF       = 40000    # 戦略②: 市区町村人口の足切り
COMP_DENSE_N     = 5        # 戦略②: 2km内競合この数以上で「競合過密」除外
DEAD_OCEAN_DEMAND = 3.0     # 戦略②: 需要複合がこの未満は「デッドオーシャン」注記

# 需要ソース（demand_backing.csv の列名 → 表示名）
DEMAND_SOURCES = {
    "fishery":       "漁業",
    "manufacturing": "製造業",
    "agriculture":   "農業",
    "commerce":      "商業",
}

WEIGHTS_1 = {  # 戦略①（合計1.0）
    "super_proximity": 0.30, "competitor_scarcity": 0.25,
    "women_pop": 0.20, "cannibal_avoid": 0.15, "roadside": 0.10,
}
WEIGHTS_2 = {  # 戦略②（合計1.0）
    "competitor_scarcity": 0.30, "demand_backing": 0.25,
    "women_pop": 0.20, "super_proximity": 0.15, "cannibal_avoid": 0.10,
}
TOP_N = 10

# ============================================================
# 距離
# ============================================================

def haversine_km_vec(lat, lon, lats, lons):
    """1点 (lat,lon) と配列 (lats,lons) の距離(km)配列"""
    R = 6371.0
    p1 = math.radians(lat)
    p2 = np.radians(lats)
    dp = np.radians(lats - lat)
    dl = np.radians(lons - lon)
    a = np.sin(dp/2)**2 + math.cos(p1)*np.cos(p2)*np.sin(dl/2)**2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))

# ============================================================
# 需要の裏付け（市区町村単位・各ソース独立）
# ============================================================

def load_demand_raw():
    """demand_backing.csv → {code: {source: value}}"""
    out = {}
    path = BASE_DIR / "demand_backing.csv"
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        code = r["code"].zfill(5)
        out[code] = {}
        for s in DEMAND_SOURCES:
            try:
                out[code][s] = float(r[s]) if r[s] not in ("", None) else 0.0
            except ValueError:
                out[code][s] = 0.0
    return out


def parent_city_code(code: str) -> str:
    """政令市の区コード(例 22101)→市コード(22100)。それ以外は自身。"""
    return code[:3] + "00"


def demand_row(demand_raw: dict, code: str) -> dict:
    """市区町村コードの需要値。自前行が無ければ政令市親へフォールバック。"""
    if code in demand_raw:
        return demand_raw[code]
    p = parent_city_code(code)
    if p in demand_raw:
        return demand_raw[p]
    return {s: 0.0 for s in DEMAND_SOURCES}


def build_demand_scores(demand_raw: dict, muni_codes: set) -> dict:
    """各ソースを市区町村単位でpercentile正規化(0-10)し、複合スコアを返す。
    戻り値: {code: {source_scores..., composite, top_source}}"""
    # 各ソースの分布（対象市区町村のみ、フォールバック適用後の値で）
    per_source_vals = {s: [] for s in DEMAND_SOURCES}
    code_vals = {}
    for code in muni_codes:
        row = demand_row(demand_raw, code)
        code_vals[code] = {s: row.get(s, 0.0) for s in DEMAND_SOURCES}
        for s in DEMAND_SOURCES:
            per_source_vals[s].append(code_vals[code][s])

    sorted_vals = {s: np.sort(np.array(v, dtype=float)) for s, v in per_source_vals.items()}

    def pctl_score(s, val):
        arr = sorted_vals[s]
        if len(arr) == 0 or val <= 0:
            return 0.0
        # 値以下の割合 → 0-10
        rank = np.searchsorted(arr, val, side="right")
        return round(rank / len(arr) * 10, 2)

    result = {}
    for code in muni_codes:
        scores = {s: pctl_score(s, code_vals[code][s]) for s in DEMAND_SOURCES}
        base = max(scores.values())
        top_source = max(scores, key=lambda k: scores[k])
        n_high = sum(1 for v in scores.values() if v >= DEMAND_HIGH)
        bonus = 0
        if n_high >= 3:
            bonus = 2
        elif n_high == 2:
            bonus = 1
        composite = round(min(10.0, base + bonus), 2)
        result[code] = {
            "source_scores": scores,
            "composite": composite,
            "top_source": DEMAND_SOURCES[top_source] if base > 0 else "なし",
        }
    return result

# ============================================================
# メイン
# ============================================================

def main():
    log.info("=== 出店候補スコアリング ===")

    # ---- 読み込み ----
    cand = json.load(open(DOCS_DATA / "lifeline_stores.json", encoding="utf-8"))
    comp = json.load(open(DOCS_DATA / "competitors_all.json", encoding="utf-8"))
    daikichi = json.load(open(DOCS_DATA / "stores.json", encoding="utf-8"))
    log.info(f"  候補:{len(cand)} 競合:{len(comp)} 大吉:{len(daikichi)}")

    comp_lat = np.array([c["latitude"] for c in comp], dtype=float)
    comp_lon = np.array([c["longitude"] for c in comp], dtype=float)
    dk_lat = np.array([s["lat"] for s in daikichi if s.get("lat")], dtype=float)
    dk_lon = np.array([s["lng"] for s in daikichi if s.get("lng")], dtype=float)
    cand_lat = np.array([c["lat"] for c in cand], dtype=float)
    cand_lon = np.array([c["lng"] for c in cand], dtype=float)

    # ---- 候補を市区町村ポリゴンに割当（人口・コード取得）----
    log.info("  市区町村割当(point-in-polygon)")
    wards = gpd.read_file(DOCS_DATA / "ward_population.geojson")[
        ["code", "city", "pref", "total_pop", "women_40plus", "geometry"]]
    wards["code"] = wards["code"].astype(str).str.zfill(5)
    pts = gpd.GeoDataFrame(
        {"idx": range(len(cand))},
        geometry=gpd.points_from_xy(cand_lon, cand_lat), crs="EPSG:4326")
    joined = gpd.sjoin(pts, wards, how="left", predicate="within").drop_duplicates("idx")
    muni = {int(r["idx"]): r for _, r in joined.iterrows()}

    # ---- 需要スコア（市区町村単位）----
    log.info("  需要の裏付け 正規化")
    demand_raw = load_demand_raw()
    muni_codes = set(str(c).zfill(5) for c in wards["code"])
    demand_scores = build_demand_scores(demand_raw, muni_codes)

    # ---- 候補ごとの指標 ----
    log.info("  候補ごとの指標計算")
    records = []
    for i, c in enumerate(cand):
        lat, lon = cand_lat[i], cand_lon[i]
        m = muni.get(i)
        if m is None or m.get("code") is None or (isinstance(m.get("code"), float) and math.isnan(m.get("code", float("nan")))):
            continue  # ポリゴン外（離島沖等）はスキップ
        code = str(m["code"]).zfill(5)
        city = m["city"]; pref = m["pref"]
        muni_pop = int(m["total_pop"]) if m["total_pop"] == m["total_pop"] else 0
        women = int(m["women_40plus"]) if m["women_40plus"] == m["women_40plus"] else 0

        # スーパー近接（自分以外の生活動線、R_SUPER_KM内）
        d_super = haversine_km_vec(lat, lon, cand_lat, cand_lon)
        near_mask = (d_super <= R_SUPER_KM) & (d_super > 1e-6)
        n_super = int(near_mask.sum())
        super_score = round(min(10.0, n_super / SUPER_CAP * 10), 2)
        near_super_names = [cand[j]["name"] for j in np.where(near_mask)[0][:5]]

        # 競合の少なさ
        d_comp = haversine_km_vec(lat, lon, comp_lat, comp_lon)
        nearest_comp = float(d_comp.min()) if len(d_comp) else 99.0
        n_comp_2km = int((d_comp <= R_COMP_KM).sum())
        dist_score = min(10.0, nearest_comp / COMP_DIST_CAP_KM * 10)
        count_score = max(0.0, 10 - n_comp_2km * 2)
        scarcity_score = round(0.6 * dist_score + 0.4 * count_score, 2)

        # 女性40+人口
        women_score = round(min(10.0, women / POP_CAP * 10), 2)

        # カニバリ回避
        d_dk = haversine_km_vec(lat, lon, dk_lat, dk_lon)
        nearest_dk = float(d_dk.min()) if len(d_dk) else 99.0
        cannibal_score = round(min(10.0, nearest_dk / CANNIBAL_CAP_KM * 10), 2)

        # ロードサイド適性（TODO: 一律）
        roadside_score = ROADSIDE_UNIFORM

        # 需要の裏付け
        dsc = demand_scores.get(code, {"composite": 0.0, "top_source": "なし",
                                       "source_scores": {s: 0.0 for s in DEMAND_SOURCES}})

        metrics = {
            "super_proximity": super_score,
            "competitor_scarcity": scarcity_score,
            "women_pop": women_score,
            "cannibal_avoid": cannibal_score,
            "roadside": roadside_score,
            "demand_backing": dsc["composite"],
        }
        s1 = round(sum(metrics[k]/10*w for k, w in WEIGHTS_1.items()) * 100, 1)
        s2 = round(sum(metrics[k]/10*w for k, w in WEIGHTS_2.items()) * 100, 1)

        records.append({
            "name": c["name"], "chain": c["chain"], "category": c["category"],
            "prefecture": pref, "city": city, "lat": round(lat,6), "lng": round(lon,6),
            "muni_code": code, "muni_pop": muni_pop, "women_40plus": women,
            "metrics": metrics,
            "demand_detail": {
                **{DEMAND_SOURCES[s]: dsc["source_scores"][s] for s in DEMAND_SOURCES},
                "top_source": dsc["top_source"], "composite": dsc["composite"],
            },
            "nearest_comp_km": round(nearest_comp, 2),
            "n_comp_2km": n_comp_2km,
            "near_super_names": near_super_names,
            "score1": s1, "score2": s2,
        })

    log.info(f"  スコア算出済み候補: {len(records)}")

    # ============================================================
    # 戦略① 上位10
    # ============================================================
    top1 = sorted(records, key=lambda r: r["score1"], reverse=True)[:TOP_N]
    for rank, r in enumerate(top1, 1):
        r1 = dict(r); r1["rank"] = rank; r1["total_score"] = r["score1"]

    out1 = []
    for rank, r in enumerate(top1, 1):
        out1.append({"rank": rank, "total_score": r["score1"], **{k: r[k] for k in
            ["name","chain","category","prefecture","city","lat","lng","muni_pop",
             "women_40plus","metrics","demand_detail","nearest_comp_km","n_comp_2km","near_super_names"]}})

    # ============================================================
    # 戦略② 足切り → 上位10
    # ============================================================
    excl_pop = excl_dense = 0
    elig2 = []
    for r in records:
        if r["muni_pop"] < POP_CUTOFF:
            excl_pop += 1; continue
        if r["n_comp_2km"] >= COMP_DENSE_N:
            excl_dense += 1; continue
        elig2.append(r)
    top2 = sorted(elig2, key=lambda r: r["score2"], reverse=True)[:TOP_N]
    out2 = []
    n_dead = 0
    for rank, r in enumerate(top2, 1):
        dead = r["demand_detail"]["composite"] < DEAD_OCEAN_DEMAND
        if dead: n_dead += 1
        out2.append({"rank": rank, "total_score": r["score2"],
            "dead_ocean": dead, **{k: r[k] for k in
            ["name","chain","category","prefecture","city","lat","lng","muni_pop",
             "women_40plus","metrics","demand_detail","nearest_comp_km","n_comp_2km","near_super_names"]}})

    json.dump(out1, open(DOCS_DATA/"ranking_strategy1.json","w",encoding="utf-8"),
              ensure_ascii=False, separators=(",",":"))
    json.dump(out2, open(DOCS_DATA/"ranking_strategy2.json","w",encoding="utf-8"),
              ensure_ascii=False, separators=(",",":"))

    # ============================================================
    # レポート出力
    # ============================================================
    log.info("=== 戦略① 上位10 ===")
    for r in out1:
        m = r["metrics"]
        log.info(f"  {r['rank']:2d}. {r['name'][:18]}({r['prefecture']}{r['city']}) "
                 f"総合{r['total_score']} [近接{m['super_proximity']}/競少{m['competitor_scarcity']}"
                 f"/人口{m['women_pop']}/カニバ{m['cannibal_avoid']}]")
    log.info("=== 戦略② 上位10 ===")
    for r in out2:
        m = r["metrics"]; dd = r["demand_detail"]
        flag = " ⚠デッドオーシャン" if r["dead_ocean"] else ""
        log.info(f"  {r['rank']:2d}. {r['name'][:18]}({r['prefecture']}{r['city']}) "
                 f"総合{r['total_score']} [競少{m['competitor_scarcity']}/需要{dd['composite']}"
                 f"({dd['top_source']})/人口{m['women_pop']}] 競合最寄{r['nearest_comp_km']}km{flag}")
    log.info(f"=== 戦略② 足切り: 人口4万未満 {excl_pop} / 競合過密 {excl_dense} / "
             f"対象 {len(elig2)} / デッドオーシャン注記 {n_dead} ===")
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
