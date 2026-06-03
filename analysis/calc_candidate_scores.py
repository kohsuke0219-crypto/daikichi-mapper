"""
出店候補地スコアリング（戦略①都内スーパー近郊 / 戦略②田舎ブルーオーシャン）

候補地点 = 生活動線レイヤー（スーパー・複合施設 #DB2777）。
各候補に周辺指標スコア(0-10)を付与し、2戦略の合成スコア(0-100)で上位10を抽出。

■ 改修1: データ粒度の使い分け（無人地帯の過大評価を防ぐ）
   ・商圏人口(40歳以上女性)は「市の総人口」ではなく、候補地点 半径2km内の
     人口点群(町丁字centroid×女性40+)の合計＝メッシュ粒度で算出。
     → 田畑・山林の中のスーパーは周辺点群が薄く自動的に低スコア。
   ・需要の裏付け(漁業/製造業/農業/商業)は市区町村単位のまま（産業的性格づけ
     としてのみ使用。人が住んでいるかの判定には使わない）。
   ・戦略②の足切りを二段化:
       1段目(地域の母数): 市区町村人口 >= 40,000
       2段目(地点の現場): 半径2km商圏人口(女性40+) >= MESH_POP_CUTOFF
         （実データ分布[2km女性40+: p10≈4,700/中央26,300]より5,000=無人地帯除外）

■ 改修2: 地理的分散オプション（市偏在の是正、DISPERSION_ON で切替）
   ・同一市区町村から採用は最大 MAX_PER_CITY(=2) 件
   ・同一市区町村内で互いに半径 COLLAPSE_RADIUS_KM(=3km) 内はスコア最上位1件に集約
   ・戦略①②の両方に適用。OFF にすれば純粋スコア順。

■ 需要の裏付けは4ソース複合に一般化（漁業/製造業/農業/商業をpercentile正規化、
   複合=max＋複数高スコアでボーナス）→ 工業町/農業町/商業町を同じ土俵で評価。

データ出所(取得日2026-06-03):
  候補/競合/大吉 = docs/data/*.json、人口点群 = analysis/pop_points.csv
  (e-Stat 統計GIS 小地域境界 × 小地域 女性40+人口)
  需要の裏付け = e-Stat 社会人口統計体系 市区町村データ C経済基盤(0000020103)
  ロードサイド適性 = 幹線道路データが一部県のみのため公平性優先で一律(TODO)

出力: docs/data/ranking_strategy1.json / ranking_strategy2.json
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
# 調整可能な定数（配点・重み・粒度・足切り・分散）
# ============================================================
R_SUPER_KM       = 1.5      # スーパー近接を数える半径
R_COMP_KM        = 2.0      # 競合をカウントする半径
SUPER_CAP        = 8        # 近接スーパーがこの数で満点
COMP_DIST_CAP_KM = 5.0      # 最寄り競合がこの距離で満点
CANNIBAL_CAP_KM  = 5.0      # 最寄り大吉がこの距離で満点
ROADSIDE_UNIFORM = 5.0      # TODO: 幹線道路データ全県整備後に置換

# 改修1: メッシュ商圏人口（女性40+）
TRADE_RADIUS_KM  = 2.0      # 商圏人口を集計する半径
TRADE_POP_CAP    = 60000    # この商圏人口(女性40+)で満点(≈分布p90)
MESH_POP_CUTOFF  = 5000     # 戦略②2段目: これ未満は無人地帯として除外(≈p10)
TRADE_THIN_POP   = 10000    # 市は大きいが商圏人口が薄い→「周辺人口希薄」注記閾値(≈p25)

# 需要
DEMAND_HIGH      = 7.0
POP_CUTOFF       = 40000    # 戦略②1段目: 市区町村人口の母数足切り
COMP_DENSE_N     = 5        # 戦略②: 2km内競合この数以上で「競合過密」除外
DEAD_OCEAN_DEMAND = 3.0     # 需要複合がこの未満は「デッドオーシャン」注記

# 改修2: 地理的分散
DISPERSION_ON       = True
MAX_PER_CITY        = 2
COLLAPSE_RADIUS_KM  = 3.0

DEMAND_SOURCES = {"fishery": "漁業", "manufacturing": "製造業",
                  "agriculture": "農業", "commerce": "商業"}

WEIGHTS_1 = {"super_proximity": 0.30, "competitor_scarcity": 0.25,
             "women_pop": 0.20, "cannibal_avoid": 0.15, "roadside": 0.10}
WEIGHTS_2 = {"competitor_scarcity": 0.30, "demand_backing": 0.25,
             "women_pop": 0.20, "super_proximity": 0.15, "cannibal_avoid": 0.10}
TOP_N = 10

# ============================================================
def haversine_km_vec(lat, lon, lats, lons):
    R = 6371.0
    p1 = math.radians(lat)
    dp = np.radians(lats - lat); dl = np.radians(lons - lon)
    a = np.sin(dp/2)**2 + math.cos(p1)*np.cos(np.radians(lats))*np.sin(dl/2)**2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2-lat1); dl = math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R*2*math.atan2(math.sqrt(a), math.sqrt(1-a))

# ---- 需要の裏付け（市区町村単位・各ソース独立 / percentile正規化）----
def load_demand_raw():
    out = {}
    for r in csv.DictReader(open(BASE_DIR/"demand_backing.csv", encoding="utf-8-sig")):
        code = r["code"].zfill(5); out[code] = {}
        for s in DEMAND_SOURCES:
            try: out[code][s] = float(r[s]) if r[s] not in ("", None) else 0.0
            except ValueError: out[code][s] = 0.0
    return out

def parent_city_code(code): return code[:3] + "00"

def demand_row(raw, code):
    if code in raw: return raw[code]
    p = parent_city_code(code)
    if p in raw: return raw[p]
    return {s: 0.0 for s in DEMAND_SOURCES}

def build_demand_scores(raw, muni_codes):
    per = {s: [] for s in DEMAND_SOURCES}; cv = {}
    for code in muni_codes:
        row = demand_row(raw, code)
        cv[code] = {s: row.get(s, 0.0) for s in DEMAND_SOURCES}
        for s in DEMAND_SOURCES: per[s].append(cv[code][s])
    sv = {s: np.sort(np.array(v, float)) for s, v in per.items()}
    def pctl(s, val):
        arr = sv[s]
        if len(arr) == 0 or val <= 0: return 0.0
        return round(np.searchsorted(arr, val, side="right")/len(arr)*10, 2)
    res = {}
    for code in muni_codes:
        sc = {s: pctl(s, cv[code][s]) for s in DEMAND_SOURCES}
        base = max(sc.values()); top = max(sc, key=lambda k: sc[k])
        n_high = sum(1 for v in sc.values() if v >= DEMAND_HIGH)
        bonus = 2 if n_high >= 3 else (1 if n_high == 2 else 0)
        res[code] = {"source_scores": sc, "composite": round(min(10.0, base+bonus), 2),
                     "top_source": DEMAND_SOURCES[top] if base > 0 else "なし"}
    return res

# ---- 地理的分散（同一市最大2件・同一市3km内集約）----
def apply_dispersion(sorted_recs, n):
    """スコア降順recordsから分散ルールでn件選ぶ。
    戻り値: (selected, skip_city_cap, skip_proximity)"""
    if not DISPERSION_ON:
        return sorted_recs[:n], [], []
    selected = []; per_city = {}; skip_cap = []; skip_prox = []
    for r in sorted_recs:
        if len(selected) >= n: break
        city = r["muni_code"]
        # 同一市3km内に採用済みがあれば集約(スキップ)
        too_close = any(s["muni_code"] == city and
                        haversine_km(r["lat"], r["lng"], s["lat"], s["lng"]) <= COLLAPSE_RADIUS_KM
                        for s in selected)
        if too_close:
            skip_prox.append(r); continue
        if per_city.get(city, 0) >= MAX_PER_CITY:
            skip_cap.append(r); continue
        selected.append(r); per_city[city] = per_city.get(city, 0) + 1
    return selected, skip_cap, skip_prox

# ============================================================
def main():
    log.info("=== 出店候補スコアリング（メッシュ商圏＋分散）===")
    cand = json.load(open(DOCS_DATA/"lifeline_stores.json", encoding="utf-8"))
    comp = json.load(open(DOCS_DATA/"competitors_all.json", encoding="utf-8"))
    daikichi = json.load(open(DOCS_DATA/"stores.json", encoding="utf-8"))
    log.info(f"  候補:{len(cand)} 競合:{len(comp)} 大吉:{len(daikichi)}")

    comp_lat = np.array([c["latitude"] for c in comp], float)
    comp_lon = np.array([c["longitude"] for c in comp], float)
    dk_lat = np.array([s["lat"] for s in daikichi if s.get("lat")], float)
    dk_lon = np.array([s["lng"] for s in daikichi if s.get("lng")], float)
    cand_lat = np.array([c["lat"] for c in cand], float)
    cand_lon = np.array([c["lng"] for c in cand], float)

    # 人口点群（メッシュ商圏用）
    prows = list(csv.reader(open(BASE_DIR/"pop_points.csv", encoding="utf-8")))[1:]
    pop_lat = np.array([float(r[0]) for r in prows])
    pop_lon = np.array([float(r[1]) for r in prows])
    pop_w   = np.array([int(r[2]) for r in prows])
    log.info(f"  人口点群:{len(prows)}")

    # 市区町村割当
    log.info("  市区町村割当(point-in-polygon)")
    wards = gpd.read_file(DOCS_DATA/"ward_population.geojson")[
        ["code","city","pref","total_pop","women_40plus","geometry"]]
    wards["code"] = wards["code"].astype(str).str.zfill(5)
    pts = gpd.GeoDataFrame({"idx": range(len(cand))},
        geometry=gpd.points_from_xy(cand_lon, cand_lat), crs="EPSG:4326")
    joined = gpd.sjoin(pts, wards, how="left", predicate="within").drop_duplicates("idx")
    muni = {int(r["idx"]): r for _, r in joined.iterrows()}

    demand_scores = build_demand_scores(load_demand_raw(),
                                        set(str(c).zfill(5) for c in wards["code"]))

    log.info("  候補ごとの指標計算（メッシュ商圏含む）")
    records = []
    for i, c in enumerate(cand):
        lat, lon = cand_lat[i], cand_lon[i]
        m = muni.get(i)
        if m is None or m.get("code") is None or (isinstance(m.get("code"), float) and m.get("code") != m.get("code")):
            continue
        code = str(m["code"]).zfill(5)
        muni_pop = int(m["total_pop"]) if m["total_pop"] == m["total_pop"] else 0
        muni_women = int(m["women_40plus"]) if m["women_40plus"] == m["women_40plus"] else 0

        # メッシュ商圏人口(女性40+, 半径2km)
        dpop = haversine_km_vec(lat, lon, pop_lat, pop_lon)
        trade_women = int(pop_w[dpop <= TRADE_RADIUS_KM].sum())
        women_score = round(min(10.0, trade_women / TRADE_POP_CAP * 10), 2)

        # スーパー近接
        d_super = haversine_km_vec(lat, lon, cand_lat, cand_lon)
        near = (d_super <= R_SUPER_KM) & (d_super > 1e-6)
        n_super = int(near.sum())
        super_score = round(min(10.0, n_super / SUPER_CAP * 10), 2)
        near_names = [cand[j]["name"] for j in np.where(near)[0][:5]]

        # 競合の少なさ
        d_comp = haversine_km_vec(lat, lon, comp_lat, comp_lon)
        nearest_comp = float(d_comp.min()) if len(d_comp) else 99.0
        n_comp2 = int((d_comp <= R_COMP_KM).sum())
        scarcity = round(0.6*min(10.0, nearest_comp/COMP_DIST_CAP_KM*10)
                         + 0.4*max(0.0, 10 - n_comp2*2), 2)

        # カニバリ回避
        d_dk = haversine_km_vec(lat, lon, dk_lat, dk_lon)
        nearest_dk = float(d_dk.min()) if len(d_dk) else 99.0
        cannibal = round(min(10.0, nearest_dk/CANNIBAL_CAP_KM*10), 2)

        dsc = demand_scores.get(code, {"composite":0.0,"top_source":"なし",
              "source_scores":{s:0.0 for s in DEMAND_SOURCES}})
        metrics = {"super_proximity": super_score, "competitor_scarcity": scarcity,
                   "women_pop": women_score, "cannibal_avoid": cannibal,
                   "roadside": ROADSIDE_UNIFORM, "demand_backing": dsc["composite"]}
        s1 = round(sum(metrics[k]/10*w for k,w in WEIGHTS_1.items())*100, 1)
        s2 = round(sum(metrics[k]/10*w for k,w in WEIGHTS_2.items())*100, 1)

        pop_sparse = (muni_pop >= POP_CUTOFF and trade_women < TRADE_THIN_POP)

        records.append({
            "name": c["name"], "chain": c["chain"], "category": c["category"],
            "prefecture": m["pref"], "city": m["city"], "lat": round(lat,6), "lng": round(lon,6),
            "muni_code": code, "muni_pop": muni_pop, "muni_women_40plus": muni_women,
            "trade_women": trade_women, "pop_sparse": pop_sparse,
            "metrics": metrics,
            "demand_detail": {**{DEMAND_SOURCES[s]: dsc["source_scores"][s] for s in DEMAND_SOURCES},
                              "top_source": dsc["top_source"], "composite": dsc["composite"]},
            "nearest_comp_km": round(nearest_comp,2), "n_comp_2km": n_comp2,
            "near_super_names": near_names, "score1": s1, "score2": s2,
        })
    log.info(f"  スコア算出済み候補: {len(records)}")

    fields = ["name","chain","category","prefecture","city","lat","lng","muni_code",
              "muni_pop","muni_women_40plus","trade_women","pop_sparse","metrics",
              "demand_detail","nearest_comp_km","n_comp_2km","near_super_names"]

    # ---- 戦略① ----
    s1sorted = sorted(records, key=lambda r: r["score1"], reverse=True)
    sel1, cap1, prox1 = apply_dispersion(s1sorted, TOP_N)
    out1 = [{"rank": i+1, "total_score": r["score1"], **{k: r[k] for k in fields}}
            for i, r in enumerate(sel1)]

    # ---- 戦略② 二段足切り ----
    excl_pop = excl_mesh = excl_dense = 0
    elig2 = []
    for r in records:
        if r["muni_pop"] < POP_CUTOFF: excl_pop += 1; continue          # 1段目: 母数不足
        if r["trade_women"] < MESH_POP_CUTOFF: excl_mesh += 1; continue # 2段目: 無人地帯
        if r["n_comp_2km"] >= COMP_DENSE_N: excl_dense += 1; continue   # 競合過密
        elig2.append(r)
    s2sorted = sorted(elig2, key=lambda r: r["score2"], reverse=True)
    sel2, cap2, prox2 = apply_dispersion(s2sorted, TOP_N)
    out2 = []
    n_dead = 0
    for i, r in enumerate(sel2):
        dead = bool(r["demand_detail"]["composite"] < DEAD_OCEAN_DEMAND)
        if dead: n_dead += 1
        out2.append({"rank": i+1, "total_score": r["score2"], "dead_ocean": dead,
                     **{k: r[k] for k in fields}})

    json.dump(out1, open(DOCS_DATA/"ranking_strategy1.json","w",encoding="utf-8"),
              ensure_ascii=False, separators=(",",":"))
    json.dump(out2, open(DOCS_DATA/"ranking_strategy2.json","w",encoding="utf-8"),
              ensure_ascii=False, separators=(",",":"))

    # ---- レポート ----
    def cz(lst):
        from collections import Counter
        return dict(Counter((r["prefecture"]+r["city"]) for r in lst))
    log.info("=== 戦略① 上位10 ===")
    for r in out1:
        m=r["metrics"]; sp=" [周辺人口希薄]" if r["pop_sparse"] else ""
        log.info(f"  {r['rank']:2d}. {r['name'][:16]}({r['prefecture']}{r['city']}) 総合{r['total_score']} "
                 f"商圏人口{r['trade_women']:,}/市{r['muni_pop']:,} 近接{m['super_proximity']} 競少{m['competitor_scarcity']}{sp}")
    log.info(f"  戦略① 分散除外: 市上限超 {len(cap1)} / 3km集約 {len(prox1)}  集約元={cz(prox1)}")
    log.info("=== 戦略② 上位10 ===")
    for r in out2:
        m=r["metrics"]; dd=r["demand_detail"]; sp=" [周辺人口希薄]" if r["pop_sparse"] else ""
        flag=" ⚠DEAD" if r["dead_ocean"] else ""
        log.info(f"  {r['rank']:2d}. {r['name'][:16]}({r['prefecture']}{r['city']}) 総合{r['total_score']} "
                 f"商圏人口{r['trade_women']:,}/市{r['muni_pop']:,} 競少{m['competitor_scarcity']} "
                 f"需要{dd['composite']}({dd['top_source']}) 競合最寄{r['nearest_comp_km']}km{sp}{flag}")
    log.info(f"  戦略② 足切り: 母数不足(人口4万未満) {excl_pop} / 無人地帯(商圏<{MESH_POP_CUTOFF}) {excl_mesh} / "
             f"競合過密 {excl_dense} / 対象 {len(elig2)}")
    log.info(f"  戦略② 分散除外: 市上限超 {len(cap2)} / 3km集約 {len(prox2)}  集約元={cz(prox2)}")
    log.info(f"  デッドオーシャン注記: {n_dead}")
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
