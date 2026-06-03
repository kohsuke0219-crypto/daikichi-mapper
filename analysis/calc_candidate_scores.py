"""
出店候補地スコアリング（戦略①都内スーパー近郊 / 戦略②田舎ブルーオーシャン）
── エリアタイプ層別・公平化版 ──

候補地点 = 生活動線レイヤー（スーパー・複合施設 #DB2777）。

■ 公平化の設計（東京と田舎を同じ物差しで比べない）
   指標スコア(0-10)は全国一律のcapではなく、候補が属する「エリアタイプ層」
   （超都心/都心住宅/郊外住宅/ロードサイド ※フェーズ12の人口密度+駅密度分類）
   の中での percentile で正規化する。
   → 「その地域タイプの中での相対的な良さ」で評価され、密度の高い都心が
     構造的に有利になる問題を解消。田舎は田舎の同類と、都心は都心の同類と比較。
   ・需要の裏付け(漁業/製造業/農業/商業)も層内percentileで正規化（複合=max+ボーナス）。
   ・ロードサイド適性は道路データ未整備県があるため一律(TODO)。

■ 絶対の足切り（生存ライン）は全国共通のまま維持
   1段目 市区町村人口 >= 40,000   2段目 半径2km商圏人口(女性40+) >= 5,000
   競合過密(2km内競合5店以上)除外。需要複合<3はデッドオーシャン注記。
   ※相対化しても「最低限の人口」は絶対基準で担保（過疎地の過大評価を防ぐ）。

■ 商圏人口はメッシュ粒度（市総人口でなく半径2km内の人口点群×女性40+の合計）
   → 田畑・山林の中のスーパーは商圏人口が薄く自動的に低評価。

■ 地理的分散（DISPERSION_ON）: 同一市区町村 最大2件 + 同一市3km内は最上位に集約。

■ 出力: エリアタイプ層ごとに上位 TOP_PER_STRATUM 件（田舎も都心も必ず代表が出る）。

データ出所(取得日2026-06-03):
  候補/競合/大吉=docs/data/*.json、人口点群=analysis/pop_points.csv、
  需要=analysis/demand_backing.csv(e-Stat 経済基盤0000020103)、
  エリアタイプ=analysis/area_classified.csv(人口密度+駅密度)
出力: docs/data/ranking_strategy1.json / ranking_strategy2.json
"""
import csv
import json
import logging
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import geopandas as gpd

BASE_DIR  = Path(__file__).parent
DOCS_DATA = BASE_DIR.parent / "docs" / "data"
LOG_PATH  = BASE_DIR / "progress.log"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()])
log = logging.getLogger(__name__)

# ============================================================
# 調整可能な定数
# ============================================================
R_SUPER_KM       = 1.5      # スーパー近接を数える半径
R_COMP_KM        = 2.0      # 競合カウント半径
ROADSIDE_UNIFORM = 5.0      # TODO: 幹線道路データ全県整備後に置換
TRADE_RADIUS_KM  = 2.0      # メッシュ商圏人口の半径

# 絶対の足切り（全国共通・生存ライン）
POP_CUTOFF        = 40000   # 戦略②1段目: 市区町村人口
MESH_POP_CUTOFF   = 5000    # 戦略②2段目: 半径2km商圏人口(女性40+)（無人地帯除外, ≈分布p10）
TRADE_THIN_POP    = 10000   # 「周辺人口希薄」注記閾値（市は大きいが商圏薄い, ≈p25）
COMP_DENSE_N      = 5       # 戦略②: 2km内競合この数以上で除外
DEAD_OCEAN_DEMAND = 3.0     # 需要複合がこの未満はデッドオーシャン注記
DEMAND_HIGH       = 7.0     # 需要ボーナス判定の閾値

# 地理的分散
DISPERSION_ON      = True
MAX_PER_CITY       = 2
COLLAPSE_RADIUS_KM = 3.0

# 出力（エリアタイプ層ごとの上位件数）
TOP_PER_STRATUM = 3
AREA_TYPE_ORDER = ["超都心", "都心住宅", "郊外住宅", "ロードサイド"]

DEMAND_SOURCES = {"fishery": "漁業", "manufacturing": "製造業",
                  "agriculture": "農業", "commerce": "商業"}

WEIGHTS_1 = {"super_proximity": 0.30, "competitor_scarcity": 0.25,
             "women_pop": 0.20, "cannibal_avoid": 0.15, "roadside": 0.10}
WEIGHTS_2 = {"competitor_scarcity": 0.30, "demand_backing": 0.25,
             "women_pop": 0.20, "super_proximity": 0.15, "cannibal_avoid": 0.10}

# ============================================================
def hv_vec(lat, lon, lats, lons):
    R = 6371.0; p1 = math.radians(lat)
    dp = np.radians(lats-lat); dl = np.radians(lons-lon)
    a = np.sin(dp/2)**2 + math.cos(p1)*np.cos(np.radians(lats))*np.sin(dl/2)**2
    return R*2*np.arctan2(np.sqrt(a), np.sqrt(1-a))

def hv(lat1, lon1, lat2, lon2):
    R = 6371.0; p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2-lat1); dl = math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R*2*math.atan2(math.sqrt(a), math.sqrt(1-a))

def pctl_within(values):
    """raw値リスト → 各値の percentile(0-10)。同集団内での相対順位。"""
    arr = np.array(values, float)
    s = np.sort(arr)
    n = len(s)
    if n == 0: return []
    return [round(np.searchsorted(s, v, side="right")/n*10, 2) for v in arr]

# ---- 需要の裏付け（層内percentile）----
def load_demand_raw():
    out = {}
    for r in csv.DictReader(open(BASE_DIR/"demand_backing.csv", encoding="utf-8-sig")):
        code = r["code"].zfill(5); out[code] = {}
        for s in DEMAND_SOURCES:
            try: out[code][s] = float(r[s]) if r[s] not in ("", None) else 0.0
            except ValueError: out[code][s] = 0.0
    return out

def demand_value(raw, code, src):
    if code in raw: return raw[code].get(src, 0.0)
    p = code[:3] + "00"  # 政令市区→市フォールバック
    if p in raw: return raw[p].get(src, 0.0)
    return 0.0

def build_demand_scores(raw, muni_area_type):
    """各ソースを『エリアタイプ層内』でpercentile正規化し複合スコアを返す。"""
    # area_type -> [code]
    groups = defaultdict(list)
    for code, at in muni_area_type.items():
        groups[at].append(code)
    # per (area_type, source): sorted raw値
    sorted_vals = {}
    for at, codes in groups.items():
        for s in DEMAND_SOURCES:
            sorted_vals[(at, s)] = np.sort(np.array([demand_value(raw, c, s) for c in codes], float))
    def pct(at, s, v):
        arr = sorted_vals.get((at, s))
        if arr is None or len(arr) == 0 or v <= 0: return 0.0
        return round(np.searchsorted(arr, v, side="right")/len(arr)*10, 2)
    res = {}
    for code, at in muni_area_type.items():
        sc = {s: pct(at, s, demand_value(raw, code, s)) for s in DEMAND_SOURCES}
        base = max(sc.values()); top = max(sc, key=lambda k: sc[k])
        nh = sum(1 for v in sc.values() if v >= DEMAND_HIGH)
        bonus = 2 if nh >= 3 else (1 if nh == 2 else 0)
        res[code] = {"source_scores": sc, "composite": round(min(10.0, base+bonus), 2),
                     "top_source": DEMAND_SOURCES[top] if base > 0 else "なし"}
    return res

# ---- 地理的分散 ----
def apply_dispersion(sorted_recs, n):
    if not DISPERSION_ON:
        return sorted_recs[:n], [], []
    sel=[]; per={}; cap=[]; prox=[]
    for r in sorted_recs:
        if len(sel) >= n: break
        city = r["muni_code"]
        if any(s["muni_code"]==city and hv(r["lat"],r["lng"],s["lat"],s["lng"])<=COLLAPSE_RADIUS_KM for s in sel):
            prox.append(r); continue
        if per.get(city,0) >= MAX_PER_CITY:
            cap.append(r); continue
        sel.append(r); per[city]=per.get(city,0)+1
    return sel, cap, prox

# ============================================================
def main():
    log.info("=== 出店候補スコアリング（エリアタイプ層別・公平化）===")
    cand = json.load(open(DOCS_DATA/"lifeline_stores.json", encoding="utf-8"))
    comp = json.load(open(DOCS_DATA/"competitors_all.json", encoding="utf-8"))
    daikichi = json.load(open(DOCS_DATA/"stores.json", encoding="utf-8"))

    comp_lat=np.array([c["latitude"] for c in comp],float); comp_lon=np.array([c["longitude"] for c in comp],float)
    dk_lat=np.array([s["lat"] for s in daikichi if s.get("lat")],float); dk_lon=np.array([s["lng"] for s in daikichi if s.get("lng")],float)
    cand_lat=np.array([c["lat"] for c in cand],float); cand_lon=np.array([c["lng"] for c in cand],float)

    prows=list(csv.reader(open(BASE_DIR/"pop_points.csv",encoding="utf-8")))[1:]
    pop_lat=np.array([float(r[0]) for r in prows]); pop_lon=np.array([float(r[1]) for r in prows]); pop_w=np.array([int(r[2]) for r in prows])
    log.info(f"  候補:{len(cand)} 競合:{len(comp)} 大吉:{len(dk_lat)} 人口点:{len(prows)}")

    # エリアタイプ（市区町村コード→type）
    muni_area_type={}
    for r in csv.DictReader(open(BASE_DIR/"area_classified.csv",encoding="utf-8-sig")):
        muni_area_type[r["code"].zfill(5)] = r["area_type"]

    # 市区町村割当
    wards=gpd.read_file(DOCS_DATA/"ward_population.geojson")[["code","city","pref","total_pop","women_40plus","geometry"]]
    wards["code"]=wards["code"].astype(str).str.zfill(5)
    pts=gpd.GeoDataFrame({"idx":range(len(cand))},geometry=gpd.points_from_xy(cand_lon,cand_lat),crs="EPSG:4326")
    joined=gpd.sjoin(pts,wards,how="left",predicate="within").drop_duplicates("idx")
    muni={int(r["idx"]):r for _,r in joined.iterrows()}

    demand_scores=build_demand_scores(load_demand_raw(), muni_area_type)

    log.info("  候補ごとの生指標を計算")
    recs=[]
    for i,c in enumerate(cand):
        lat,lon=cand_lat[i],cand_lon[i]; m=muni.get(i)
        if m is None or m.get("code") is None or (isinstance(m.get("code"),float) and m.get("code")!=m.get("code")):
            continue
        code=str(m["code"]).zfill(5)
        at=muni_area_type.get(code,"ロードサイド")
        muni_pop=int(m["total_pop"]) if m["total_pop"]==m["total_pop"] else 0
        muni_women=int(m["women_40plus"]) if m["women_40plus"]==m["women_40plus"] else 0
        # 生指標
        dpop=hv_vec(lat,lon,pop_lat,pop_lon); trade_women=int(pop_w[dpop<=TRADE_RADIUS_KM].sum())
        dsup=hv_vec(lat,lon,cand_lat,cand_lon); near=(dsup<=R_SUPER_KM)&(dsup>1e-6); n_super=int(near.sum())
        near_names=[cand[j]["name"] for j in np.where(near)[0][:5]]
        dcomp=hv_vec(lat,lon,comp_lat,comp_lon); nearest_comp=float(dcomp.min()) if len(dcomp) else 99.0
        n_comp2=int((dcomp<=R_COMP_KM).sum())
        scarcity_raw=nearest_comp/(1+n_comp2)   # 遠い&少ないほど高い（層内で相対化）
        ddk=hv_vec(lat,lon,dk_lat,dk_lon); nearest_dk=float(ddk.min()) if len(ddk) else 99.0
        dsc=demand_scores.get(code,{"composite":0.0,"top_source":"なし","source_scores":{s:0.0 for s in DEMAND_SOURCES}})
        recs.append({"name":c["name"],"chain":c["chain"],"category":c["category"],
            "prefecture":m["pref"],"city":m["city"],"lat":round(lat,6),"lng":round(lon,6),
            "muni_code":code,"area_type":at,"muni_pop":muni_pop,"muni_women_40plus":muni_women,
            "trade_women":trade_women,"pop_sparse":bool(muni_pop>=POP_CUTOFF and trade_women<TRADE_THIN_POP),
            "raw":{"super":n_super,"women":trade_women,"scarcity":scarcity_raw,"cannibal":nearest_dk},
            "demand_detail":{**{DEMAND_SOURCES[s]:dsc["source_scores"][s] for s in DEMAND_SOURCES},
                             "top_source":dsc["top_source"],"composite":dsc["composite"]},
            "nearest_comp_km":round(nearest_comp,2),"n_comp_2km":n_comp2,"near_super_names":near_names})
    log.info(f"  候補(市区町村内): {len(recs)}")

    # ---- エリアタイプ層内 percentile 正規化（4つの空間指標）----
    log.info("  エリアタイプ層内で percentile 正規化")
    by_at=defaultdict(list)
    for r in recs: by_at[r["area_type"]].append(r)
    for at, group in by_at.items():
        for key in ("super","women","scarcity","cannibal"):
            scores=pctl_within([g["raw"][key] for g in group])
            for g,sc in zip(group,scores): g.setdefault("_norm",{})[key]=sc
    # メトリクス確定（demandは層内percentile済み、roadsideは一律）
    for r in recs:
        nm=r["_norm"]
        r["metrics"]={"super_proximity":nm["super"],"competitor_scarcity":nm["scarcity"],
                      "women_pop":nm["women"],"cannibal_avoid":nm["cannibal"],
                      "roadside":ROADSIDE_UNIFORM,"demand_backing":r["demand_detail"]["composite"]}
        r["score1"]=round(sum(r["metrics"][k]/10*w for k,w in WEIGHTS_1.items())*100,1)
        r["score2"]=round(sum(r["metrics"][k]/10*w for k,w in WEIGHTS_2.items())*100,1)

    fields=["name","chain","category","prefecture","city","lat","lng","muni_code","area_type",
            "muni_pop","muni_women_40plus","trade_women","pop_sparse","metrics","demand_detail",
            "nearest_comp_km","n_comp_2km","near_super_names"]

    # ============================================================
    # 戦略①: 層ごとに上位N（足切りなし）
    # ============================================================
    out1=[]; disp1={}
    for at in AREA_TYPE_ORDER:
        g=sorted([r for r in recs if r["area_type"]==at], key=lambda r:r["score1"], reverse=True)
        sel,cap,prox=apply_dispersion(g,TOP_PER_STRATUM)
        disp1[at]=(len(cap),len(prox))
        for rank,r in enumerate(sel,1):
            out1.append({"area_type":at,"rank":rank,"total_score":r["score1"],**{k:r[k] for k in fields}})

    # ============================================================
    # 戦略②: 絶対足切り → 層ごとに上位N
    # ============================================================
    excl_pop=excl_mesh=excl_dense=0; elig=[]
    for r in recs:
        if r["muni_pop"]<POP_CUTOFF: excl_pop+=1; continue
        if r["trade_women"]<MESH_POP_CUTOFF: excl_mesh+=1; continue
        if r["n_comp_2km"]>=COMP_DENSE_N: excl_dense+=1; continue
        elig.append(r)
    out2=[]; disp2={}; n_dead=0
    for at in AREA_TYPE_ORDER:
        g=sorted([r for r in elig if r["area_type"]==at], key=lambda r:r["score2"], reverse=True)
        sel,cap,prox=apply_dispersion(g,TOP_PER_STRATUM)
        disp2[at]=(len(cap),len(prox))
        for rank,r in enumerate(sel,1):
            dead=bool(r["demand_detail"]["composite"]<DEAD_OCEAN_DEMAND)
            if dead: n_dead+=1
            out2.append({"area_type":at,"rank":rank,"total_score":r["score2"],"dead_ocean":dead,
                         **{k:r[k] for k in fields}})

    json.dump(out1,open(DOCS_DATA/"ranking_strategy1.json","w",encoding="utf-8"),ensure_ascii=False,separators=(",",":"))
    json.dump(out2,open(DOCS_DATA/"ranking_strategy2.json","w",encoding="utf-8"),ensure_ascii=False,separators=(",",":"))

    # ---- レポート ----
    for label,out,disp in [("戦略①",out1,disp1),("戦略②",out2,disp2)]:
        log.info(f"=== {label}（エリアタイプ層別 各上位{TOP_PER_STRATUM}）===")
        for at in AREA_TYPE_ORDER:
            for r in [x for x in out if x["area_type"]==at]:
                m=r["metrics"]; dd=r["demand_detail"]
                sp=" [周辺人口希薄]" if r["pop_sparse"] else ""
                d2=f" 需要{dd['composite']}({dd['top_source']})" if label=="戦略②" else ""
                dead=" ⚠DEAD" if r.get("dead_ocean") else ""
                log.info(f"  [{at}]{r['rank']}. {r['name'][:14]}({r['prefecture']}{r['city']}) "
                         f"総合{r['total_score']} 商圏{r['trade_women']:,}/市{r['muni_pop']:,} "
                         f"近接{m['super_proximity']} 競少{m['competitor_scarcity']}{d2}{sp}{dead}")
            cap,prox=disp.get(at,(0,0))
            log.info(f"    [{at}] 分散除外: 市上限超{cap} / 3km集約{prox}")
    log.info(f"戦略② 足切り: 母数不足(人口4万未満){excl_pop} / 無人地帯(商圏<{MESH_POP_CUTOFF}){excl_mesh} / "
             f"競合過密{excl_dense} / 対象{len(elig)} / デッドオーシャン注記{n_dead}")
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
