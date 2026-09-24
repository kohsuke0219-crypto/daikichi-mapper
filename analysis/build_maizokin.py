# -*- coding: utf-8 -*-
"""埋蔵金マップ（家庭に眠る動産の推計額）を町丁目ごとに作る。
推計額 = 町丁目の年齢別人口 × 年齢別1人あたり"かくれ資産"額 × 地域補正。
- 境界/総人口/面積: 2020国勢調査 小地域境界 r2ka{11,13,14}.shp（既存 smallarea_*.zip）
- 年齢別人口: analysis/geo_data/agesa_{pref}.parquet（e-Stat小地域 男女5歳階級。別途取得）
- 基準値: メルカリ2025"かくれ資産"調査（analysis/maizokin_params.json に記録）
- 地域補正: 市区町村別 課税対象所得/納税者（任意, 0.7〜1.5にclamp）
出力: docs/data/maizokin/{pref}.geojson + index.json（allow_nan=False）, maizokin_by_station.json
コマンド: base（境界ベース確認） / build（本生成） / station（駅別集計）
"""
import json, sys, math
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd

BASE = Path(__file__).parent
GEO = BASE / "geo_data"
DOCS = BASE.parent / "docs" / "data"
OUTDIR = DOCS / "maizokin"
PARAMS = BASE / "maizokin_params.json"      # メルカリ基準値（別途記録）
INCOME = BASE / "maizokin_income.json"       # 市区町村別 課税対象所得/納税者（任意）
STATIONS = DOCS / "stations_ridership.json"
PREFS = {"11": "埼玉県", "13": "東京都", "14": "神奈川県"}

AGE_BANDS = ["0_4","5_9","10_14","15_19","20_24","25_29","30_34","35_39","40_44",
             "45_49","50_54","55_59","60_64","65_69","70_74","75_79","80_84","85plus"]
BAND_LO = {b:int(b.split("_")[0].replace("plus","")) for b in AGE_BANDS}
BAND_LO["85plus"] = 85

def load_base(pref):
    g = gpd.read_file(f"zip://{GEO}/smallarea_{pref}.zip")
    g = g[g["JINKO"].fillna(0) > 0].copy()
    g["KEY_CODE"] = g["KEY_CODE"].astype(str)
    g["pref_name"] = PREFS[pref]
    g["city"] = g["CITY_NAME"].fillna("")
    g["s_name"] = g["S_NAME"].fillna("")
    g["total_pop"] = g["JINKO"].astype(int)
    g["area_km2"] = (g["AREA"].astype(float) / 1e6).round(4)
    g["lng"] = g["X_CODE"].astype(float); g["lat"] = g["Y_CODE"].astype(float)
    g = g.to_crs(4326)
    g["geometry"] = g.geometry.simplify(0.00009, preserve_topology=True)
    return g[["KEY_CODE","pref_name","city","s_name","total_pop","area_km2","lng","lat","geometry"]]

def cmd_base():
    tot=0
    for p in PREFS:
        g=load_base(p)
        tot+=len(g)
        print(f"{PREFS[p]}({p}): {len(g)}町丁目 / 人口{g['total_pop'].sum():,} / 面積{g['area_km2'].sum():.0f}km2")
    print("合計町丁目:", tot)


def _round_geo(geo, nd=5):
    """geometryの座標を小数nd桁に丸める（ファイルサイズ削減）。"""
    def rc(c):
        if isinstance(c, (list, tuple)):
            if c and isinstance(c[0], (int, float)):
                return [round(float(c[0]), nd), round(float(c[1]), nd)]
            return [rc(x) for x in c]
        return c
    geo = dict(geo); geo["coordinates"] = rc(geo["coordinates"]); return geo

def load_age(pref):
    fp = GEO / f"agesa_{pref}.parquet"
    if not fp.exists():
        raise SystemExit(f"[ERR] 年齢別人口 {fp.name} が無い。先に取得してください。")
    a = pd.read_parquet(fp)
    a["KEY_CODE"] = a["KEY_CODE"].astype(str)
    return a

def compute_pref(pref, params, income):
    g = load_base(pref)
    a = load_age(pref)
    df = g.merge(a, on="KEY_CODE", how="left")
    pc = params["per_capita_by_band_yen"]
    has_sex = all(f"m_{b}" in df.columns for b in AGE_BANDS) and all(f"f_{b}" in df.columns for b in AGE_BANDS)
    # 各バンド人口（男女計）
    band_pop = {}
    for b in AGE_BANDS:
        if has_sex:
            band_pop[b] = df[f"m_{b}"].fillna(0).values + df[f"f_{b}"].fillna(0).values
        elif f"t_{b}" in df.columns:
            band_pop[b] = df[f"t_{b}"].fillna(0).values
        else:
            band_pop[b] = np.zeros(len(df))
    # 総額(円) = Σ pop_band × percapita_band
    total_yen = np.zeros(len(df))
    for b in AGE_BANDS:
        total_yen += band_pop[b] * float(pc.get(b, 0))
    # 65歳以上 / 女性50歳以上
    pop65 = np.zeros(len(df)); fem50 = np.zeros(len(df)); fem50_ok = has_sex
    for b in ["65_69","70_74","75_79","80_84","85plus"]:
        pop65 += band_pop[b]
    if has_sex:
        for b in ["50_54","55_59","60_64","65_69","70_74","75_79","80_84","85plus"]:
            fem50 += df[f"f_{b}"].fillna(0).values
    # 年齢別人口の合計（agesa側）が無い町丁目は総人口(境界JINKO)×平均でフォールバック
    age_sum = sum(band_pop[b] for b in AGE_BANDS)
    miss = age_sum <= 0
    if miss.any():
        total_yen = np.where(miss, df["total_pop"].values * params["per_capita_avg_yen"], total_yen)
    # 地域補正
    factor = np.ones(len(df))
    if income and income.get("by_city") and params.get("region_correction",{}).get("enabled"):
        navg = income["national_avg_yen"]; lo,hi = params["region_correction"]["clamp"]
        bycity = income["by_city"]
        # 政令市の区コード→市コード（課税所得は市単位でしか無いため）
        def to_city(c):
            if c in bycity: return c
            n=int(c)
            if 11101<=n<=11119: return "11100"   # さいたま市
            if 14101<=n<=14118: return "14100"   # 横浜市
            if 14131<=n<=14137: return "14130"   # 川崎市
            if 14151<=n<=14153: return "14150"   # 相模原市
            return c
        code5 = df["KEY_CODE"].str[:5]
        fac = code5.map(lambda c: (bycity.get(to_city(c))/navg) if bycity.get(to_city(c)) else 1.0).astype(float)
        factor = fac.clip(lo,hi).values
    total_yen = total_yen * factor
    share = (params.get("buyback_share_pct") or 0)/100.0
    buyback_yen = total_yen * share
    # 億円
    df["total_oku"] = np.round(total_yen/1e8, 3)
    df["buyback_oku"] = np.round(buyback_yen/1e8, 3)
    df["pop65"] = pop65.astype(int)
    df["fem50"] = (fem50.astype(int) if fem50_ok else -1)   # -1 = 男女別なし
    df["factor"] = np.round(factor,3)
    df["buyback_per_km2"] = np.round(np.where(df["area_km2"]>0, df["buyback_oku"]/df["area_km2"], 0),3)
    df["total_per_km2"] = np.round(np.where(df["area_km2"]>0, df["total_oku"]/df["area_km2"],0),3)
    return df

def cmd_build():
    params = json.loads(PARAMS.read_text(encoding="utf-8"))
    if not params.get("buyback_share_pct"):
        raise SystemExit("[ERR] buyback_share_pct 未設定。maizokin_params.json を確定してください。")
    income = json.loads(INCOME.read_text(encoding="utf-8")) if INCOME.exists() else None
    OUTDIR.mkdir(parents=True, exist_ok=True)
    idx = []; grand = {}
    allrows = []
    for p in PREFS:
        df = compute_pref(p, params, income)
        feats = []
        for _, r in df.iterrows():
            if r.geometry is None or r.geometry.is_empty: continue
            geo = _round_geo(r.geometry.__geo_interface__)
            feats.append({"type":"Feature","properties":{
                "key": r["KEY_CODE"], "name": f'{r["city"]}{r["s_name"]}',
                "city": r["city"], "pref": r["pref_name"],
                "pop": int(r["total_pop"]), "pop65": int(r["pop65"]),
                "fem50": (int(r["fem50"]) if r["fem50"]>=0 else None),
                "area": round(float(r["area_km2"]),4),
                "total": float(r["total_oku"]), "buy": float(r["buyback_oku"]),
                "buy_km2": float(r["buyback_per_km2"]), "total_km2": float(r["total_per_km2"]),
                "lat": round(float(r["lat"]),6), "lng": round(float(r["lng"]),6),
            },"geometry": geo})
        fc = {"type":"FeatureCollection","features":feats}
        (OUTDIR / f"{p}.geojson").write_text(json.dumps(fc, ensure_ascii=False, separators=(",",":"), allow_nan=False), encoding="utf-8")
        b = df.total_bounds
        idx.append({"pref":p,"name":PREFS[p],"file":f"{p}.geojson","n":len(feats),
                    "bbox":[round(b[0],4),round(b[1],4),round(b[2],4),round(b[3],4)]})
        grand[PREFS[p]] = {"町丁目":len(feats),"総額億円":round(df["total_oku"].sum(),1),"買取向け億円":round(df["buyback_oku"].sum(),1)}
        allrows.append(df[["KEY_CODE","pref_name","city","s_name","lat","lng","total_oku","buyback_oku","buyback_per_km2","pop65","fem50"]].copy())
        print(f"{PREFS[p]}: {len(feats)}町丁目 総額{df['total_oku'].sum():,.0f}億円 買取向け{df['buyback_oku'].sum():,.0f}億円", flush=True)
    meta = {"note":"推計値（メルカリ\"かくれ資産\"調査×2020国勢調査の年齢別人口）。実際の保有額ではありません。",
            "params_source": params["source"], "buyback_share_pct": params["buyback_share_pct"],
            "region_correction": params.get("region_correction",{}).get("enabled",False),
            "generated":"2026-09-24","prefs": idx}
    (OUTDIR / "index.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",",":"), allow_nan=False), encoding="utf-8")
    print("合計:", json.dumps(grand, ensure_ascii=False))
    # トップ10（買取向け額）
    allc = pd.concat(allrows, ignore_index=True)
    top = allc.sort_values("buyback_oku", ascending=False).head(10)
    print("買取向けトップ10:")
    for _,r in top.iterrows():
        print(f"  {r['pref_name']}{r['city']}{r['s_name']}: 買取{r['buyback_oku']:.1f}億円 (総{r['total_oku']:.1f}億)")
    # 半径集計用の軽量ポイント（[lat,lng,買取向け億円]）
    ptrows = [[round(float(r["lat"]),6), round(float(r["lng"]),6), float(r["buyback_oku"])] for _,r in allc.iterrows()]
    (DOCS / "maizokin_points.json").write_text(json.dumps({"note":"町丁目centroidと買取向け額(億円)。半径集計用。","pts":ptrows}, ensure_ascii=False, separators=(",",":"), allow_nan=False), encoding="utf-8")
    print(f"points: {len(ptrows)} -> maizokin_points.json")
    # 分位（地図の色分け閾値決めに）
    qs=[0.5,0.7,0.85,0.95]
    for col in ["buyback_per_km2","total_per_km2","buyback_oku","total_oku"]:
        v = allc[col].replace([np.inf,-np.inf],np.nan).dropna()
        print(f"{col} 分位:", {q: round(float(v.quantile(q)),2) for q in qs})

def cmd_station():
    import scipy.spatial as sp
    params = json.loads(PARAMS.read_text(encoding="utf-8"))
    income = json.loads(INCOME.read_text(encoding="utf-8")) if INCOME.exists() else None
    pts=[]
    for p in PREFS:
        df = compute_pref(p, params, income)
        for _,r in df.iterrows():
            pts.append((r["lat"], r["lng"], float(r["buyback_oku"])))
    st = json.loads(STATIONS.read_text(encoding="utf-8"))
    arr = np.array([(a,b) for a,b,c in pts]); val=np.array([c for a,b,c in pts])
    # metric tree
    g = gpd.GeoDataFrame(geometry=gpd.points_from_xy(arr[:,1],arr[:,0]), crs=4326).to_crs("EPSG:6677")
    P = np.c_[g.geometry.x.values, g.geometry.y.values]
    tree = sp.cKDTree(P)
    out=[]
    for s in st:
        if not (s.get("lat") and s.get("lng")): continue
        gp = gpd.GeoSeries([__import__("shapely").geometry.Point(s["lng"],s["lat"])], crs=4326).to_crs("EPSG:6677")
        xy=np.array([gp.x.values[0], gp.y.values[0]])
        for rad,key in [(500,"buy_500m"),(1000,"buy_1km")]:
            ii = tree.query_ball_point(xy, r=rad)
            s[key] = round(float(val[ii].sum()),2)
        out.append({"name":s.get("name"),"lat":s["lat"],"lng":s["lng"],
                    "total":s.get("total"),"buy_500m":s["buy_500m"],"buy_1km":s["buy_1km"]})
    (DOCS / "maizokin_by_station.json").write_text(json.dumps({"note":"各駅から半径内の町丁目centroidの買取向け額(億円)合計。推計値。","stations":out}, ensure_ascii=False, separators=(",",":"), allow_nan=False), encoding="utf-8")
    print(f"駅別: {len(out)}駅 -> maizokin_by_station.json")
    tops=sorted(out,key=lambda x:x["buy_1km"],reverse=True)[:10]
    for t in tops: print(f"  {t['name']}: 1km {t['buy_1km']:.1f}億円 / 500m {t['buy_500m']:.1f}億円")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "base"
    if cmd == "base": cmd_base()
    elif cmd == "build": cmd_build()
    elif cmd == "station": cmd_station()
