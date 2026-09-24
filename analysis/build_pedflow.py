# -*- coding: utf-8 -*-
"""通り別 人流（推計）レイヤー生成。
OSM(Geofabrik Kanto pbf)の歩行者が通る道に、people_flow_1km(平日昼)を
道路の格・沿道店舗数・駅近接で重み付けして比例配分（人流指数=推計）。
対象: 東京都・神奈川県・埼玉県。出力は2次メッシュ別に docs/data/pedflow/。
Stage A(抽出) と Stage B(配分) に分割。引数 a / b / ab。
"""
import io, json, math, os, re, sys
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd

BASE = Path(__file__).parent
GEO = BASE / "geo_data"
PBF = GEO / "kanto-latest.osm.pbf"
ROADS_PQ = GEO / "pedflow_roads.parquet"
POIS_PQ = GEO / "pedflow_pois.parquet"
DOCS = BASE.parent / "docs" / "data"
OUTDIR = DOCS / "pedflow"
WARD = DOCS / "ward_population.geojson"
FLOW = DOCS / "people_flow_1km.json"
STATIONS = DOCS / "stations_ridership.json"

BBOX = (138.60, 35.00, 140.35, 36.30)   # 東京・神奈川・埼玉を包む矩形
TARGET_PREF = {"東京都", "神奈川県", "埼玉県", "神奈川"}
# 歩行者が通る道の格の重み（motorway/trunk除外。容量対策で residential/footway/unclassified も除外）
CLASS_W = {
    "primary": 1.0, "primary_link": 0.7, "secondary": 0.9, "secondary_link": 0.6,
    "tertiary": 0.8, "tertiary_link": 0.5, "pedestrian": 1.1, "living_street": 0.6,
}
METRIC = "EPSG:6677"
CALIB = BASE / "pedflow_calib.json"   # 実測較正の係数（無ければ既定値=較正なし）

def load_calib():
    """重み式 w = clsW^A * (1 + B*shops) * (0.4 + st_factor)^C の係数。
    既定 (A,B,C)=(1.0,0.5,1.0) は較正なし（従来出力と完全一致）。"""
    a, b, c = 1.0, 0.5, 1.0
    try:
        if CALIB.exists():
            d = json.loads(CALIB.read_text(encoding="utf-8"))
            a = float(d.get("A", a)); b = float(d.get("B", b)); c = float(d.get("C", c))
    except Exception as e:
        print(f"    [calib] 読込失敗→既定値を使用: {e}", flush=True)
    return a, b, c


def stage_a():
    cls = "','".join(CLASS_W.keys())
    print("[A] lines 読込(bbox+where)…", flush=True)
    lines = gpd.read_file(PBF, layer="lines", bbox=BBOX,
                          where=f"highway IN ('{cls}')")
    lines = lines[["osm_id", "name", "highway", "geometry"]]
    lines.to_parquet(ROADS_PQ)
    print(f"    roads: {len(lines)}  -> {ROADS_PQ.name}", flush=True)
    print("[A] points 読込(bbox+where)…", flush=True)
    pts = gpd.read_file(PBF, layer="points", bbox=BBOX,
                        where="other_tags LIKE '%\"shop\"=>%' OR other_tags LIKE '%\"amenity\"=>%'")
    pts = pts[["osm_id", "other_tags", "geometry"]].copy()
    pts.to_parquet(POIS_PQ)
    print(f"    pois: {len(pts)}  -> {POIS_PQ.name}", flush=True)
    print("[A] 完了", flush=True)


def mesh_codes(lat, lng):
    """3次(1km)8桁 と 2次(10km)6桁 を返す"""
    p = int(lat * 1.5); q = int(lng - 100)
    la2 = (lat * 1.5 - p) * 8; lo2 = (lng - 100 - q) * 8
    r = int(la2); s = int(lo2)
    la3 = (la2 - r) * 10; lo3 = (lo2 - s) * 10
    t = int(la3); u = int(lo3)
    c1 = f"{p:02d}{q:02d}"; c2 = f"{r}{s}"; c3 = f"{t}{u}"
    return c1 + c2 + c3, c1 + c2


def compute_components():
    """道路区間ごとの重み成分（clsW, shops, stf, m8/m6, wd）を計算して返す。
    A/B/C は適用しない（stage_b と calib で共用）。"""
    import scipy.spatial as sp
    print("[components] 読込", flush=True)
    roads = gpd.read_parquet(ROADS_PQ).to_crs(4326)
    pois = gpd.read_parquet(POIS_PQ).to_crs(4326)
    flow = json.loads(FLOW.read_text(encoding="utf-8"))
    st = json.loads(STATIONS.read_text(encoding="utf-8"))
    wards = gpd.read_file(WARD)[["pref", "geometry"]]

    roads = roads[roads.geometry.notna() & (roads.geometry.geom_type == "LineString")].copy()
    mid = roads.geometry.interpolate(0.5, normalized=True)
    roads["lng"] = mid.x; roads["lat"] = mid.y

    mp = gpd.GeoDataFrame(roads.drop(columns="geometry"), geometry=mid, crs=4326)
    j = gpd.sjoin(mp, wards, how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")]
    prefn = {"神奈川": "神奈川県"}
    j["pref"] = j["pref"].map(lambda x: prefn.get(x, x))
    roads = roads.loc[j["pref"].isin({"東京都", "神奈川県", "埼玉県"}).values].copy()
    roads["lng"] = mid.loc[roads.index].x; roads["lat"] = mid.loc[roads.index].y
    print(f"    3府県内 道路区間: {len(roads)}", flush=True)

    roads_m = roads.to_crs(METRIC)
    rmx = roads_m.geometry.interpolate(0.5, normalized=True)
    rx = np.c_[rmx.x.values, rmx.y.values]
    pois_m = pois.to_crs(METRIC)
    px = np.c_[pois_m.geometry.x.values, pois_m.geometry.y.values]
    ptree = sp.cKDTree(px) if len(px) else None
    shops = np.zeros(len(rx), dtype=int)
    if ptree is not None:
        near = ptree.query_ball_point(rx, r=50)
        shops = np.array([len(a) for a in near])
    sxy = []; sride = []
    for s in st:
        if s.get("lat") and s.get("lng"):
            sxy.append((s["lng"], s["lat"])); sride.append(s.get("total", 0) or 0)
    sgdf = gpd.GeoDataFrame(geometry=gpd.points_from_xy([a[0] for a in sxy], [a[1] for a in sxy]), crs=4326).to_crs(METRIC)
    smat = np.c_[sgdf.geometry.x.values, sgdf.geometry.y.values]
    stree = sp.cKDTree(smat)
    dist, idxs = stree.query(rx, k=1)
    dist_km = dist / 1000.0
    ride = np.array(sride)[idxs]
    st_factor = (1 + np.log10(1 + ride) / 3.0) * np.exp(-dist_km / 0.8)

    roads["clsW"] = roads["highway"].map(CLASS_W).fillna(0.4).values
    roads["shops"] = shops
    roads["stf"] = st_factor
    roads["st_km"] = np.round(dist_km, 2)
    m8 = []; m6 = []
    for la, lo in zip(roads["lat"].values, roads["lng"].values):
        a, b = mesh_codes(la, lo); m8.append(a); m6.append(b)
    roads["m8"] = m8; roads["m6"] = m6
    roads["wd"] = roads["m8"].map(lambda m: (flow.get(m, {}) or {}).get("wd_day", 0)).astype(float)
    return roads


def apply_idx(roads, A, B, C):
    """成分と係数(A,B,C)から人流指数 idx を計算した列を付けて返す（idx>0のみ）。"""
    w = (roads["clsW"].values ** A) * (1 + B * roads["shops"].values) * ((0.4 + roads["stf"].values) ** C)
    roads = roads.copy(); roads["w"] = w
    wsum = roads.groupby("m8")["w"].transform("sum")
    roads["idx"] = np.where(wsum > 0, roads["wd"] * roads["w"] / wsum, 0.0)
    roads = roads[roads["idx"] > 0].copy()
    roads["idx"] = roads["idx"].round().astype(int)
    return roads


def stage_b():
    roads = compute_components()
    A, B, C = load_calib()
    print(f"    重み係数 (A,B,C)=({A},{B},{C})", flush=True)
    roads = apply_idx(roads, A, B, C)
    print(f"    出力対象区間: {len(roads)}", flush=True)

    # 2次メッシュ別 geojson 出力（座標5桁・簡略化）
    OUTDIR.mkdir(parents=True, exist_ok=True)
    for f in OUTDIR.glob("*.geojson"): f.unlink()
    roads = roads.to_crs(4326)
    roads["geometry"] = roads.geometry.simplify(0.00003, preserve_topology=False)
    tiles = []
    for m6v, grp in roads.groupby("m6"):
        feats = []
        for _, r in grp.iterrows():
            if r.geometry.is_empty: continue
            coords = [[round(x, 5), round(y, 5)] for x, y in r.geometry.coords]
            road_name = "" if pd.isna(r["name"]) else str(r["name"])
            cls = "" if pd.isna(r["highway"]) else str(r["highway"])
            mesh8 = "" if pd.isna(r["m8"]) else str(r["m8"])
            feats.append({"type": "Feature",
                "properties": {"idx": int(r["idx"]), "road": road_name, "cls": cls,
                               "shops": int(r["shops"]), "st_km": float(r["st_km"]), "mesh": mesh8},
                "geometry": {"type": "LineString", "coordinates": coords}})
        if not feats: continue
        gj = {"type": "FeatureCollection", "features": feats}
        (OUTDIR / f"{m6v}.geojson").write_text(json.dumps(gj, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        # タイルbbox
        b = grp.total_bounds
        tiles.append({"code": m6v, "bbox": [round(b[0],4), round(b[1],4), round(b[2],4), round(b[3],4)], "n": len(feats)})
    (OUTDIR / "index.json").write_text(json.dumps({"tiles": tiles}, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    tot = sum(t["n"] for t in tiles)
    sz = sum(f.stat().st_size for f in OUTDIR.glob("*.geojson"))
    print(f"[B] タイル{len(tiles)}枚 / 区間{tot} / 合計{sz//1024}KB", flush=True)


def _idx_full(roads, A, B, C):
    """全区間のidxを（0含め）順序を保って返す numpy 配列。"""
    w = (roads["clsW"].values ** A) * (1 + B * roads["shops"].values) * ((0.4 + roads["stf"].values) ** C)
    tmp = roads[["m8"]].copy(); tmp["w"] = w
    wsum = tmp.groupby("m8")["w"].transform("sum").values
    idx = np.where(wsum > 0, roads["wd"].values * w / wsum, 0.0)
    return idx


def calib():
    """実測(pedestrian_counts.json)で推計を検証・較正。
    各実測点を最寄り推計区間に対応づけ、人流指数と per_hour の相関を出す。
    重み係数(A,B,C)をグリッド探索し、改善すれば pedflow_calib.json に書き出す。"""
    import scipy.spatial as sp
    from scipy.stats import spearmanr, pearsonr
    PC = BASE.parent / "docs" / "data" / "pedestrian_counts.json"
    pc = json.loads(PC.read_text(encoding="utf-8"))["points"]
    roads = compute_components()
    # 区間midpointを EPSG:6677 で
    rm = roads.to_crs(METRIC)
    mid = rm.geometry.interpolate(0.5, normalized=True)
    seg = np.c_[mid.x.values, mid.y.values]
    tree = sp.cKDTree(seg)
    # 実測点を 6677 に
    import pandas as _pd
    pts = [p for p in pc if p.get("lat") and p.get("lng")]
    g = gpd.GeoDataFrame(geometry=gpd.points_from_xy([p["lng"] for p in pts], [p["lat"] for p in pts]), crs=4326).to_crs(METRIC)
    P = np.c_[g.geometry.x.values, g.geometry.y.values]
    dist, sidx = tree.query(P, k=1)
    per_hour = np.array([p["per_hour"] for p in pts], dtype=float)
    prec = np.array([p.get("precision","area") for p in pts])
    def corr(A,B,C, mask):
        idx = _idx_full(roads, A, B, C)[sidx]
        m = mask & (idx > 0) & (per_hour > 0)
        if m.sum() < 8: return None, None, int(m.sum())
        sr = spearmanr(idx[m], per_hour[m]).correlation
        pr = pearsonr(np.log(idx[m]), np.log(per_hour[m]))[0]
        return sr, pr, int(m.sum())
    for label, radius in [("50m",50),("150m",150),("300m",300)]:
        print(f"[match] {label}以内: {(dist<=radius).sum()}/{len(dist)}点", flush=True)
    # 較正前後（street精度優先だが少数なので全点でも評価）
    for setname, mask in [("全点(300m内)", dist<=300), ("street精度(300m内)", (dist<=300)&(prec=="street"))]:
        sr0,pr0,n0 = corr(1.0,0.5,1.0, mask)
        print(f"[before] {setname} n={n0} Spearman={sr0} logPearson={pr0}", flush=True)
        best=(sr0 or -9, 1.0,0.5,1.0)
        for A in [0.6,0.8,1.0,1.2,1.5]:
            for B in [0.1,0.3,0.5,0.8,1.2]:
                for C in [0.6,1.0,1.5,2.0]:
                    sr,_,n = corr(A,B,C, mask)
                    if sr is not None and sr>best[0]: best=(sr,A,B,C)
        print(f"[grid]   {setname} best Spearman={best[0]:.3f} @ (A,B,C)=({best[1]},{best[2]},{best[3]})", flush=True)
    # 採否：全点(300m内)で改善が+0.05以上なら採用
    sr0,_,_ = corr(1.0,0.5,1.0, dist<=300)
    best=(sr0 or -9,1.0,0.5,1.0)
    for A in [0.6,0.8,1.0,1.2,1.5]:
        for B in [0.1,0.3,0.5,0.8,1.2]:
            for C in [0.6,1.0,1.5,2.0]:
                sr,_,_=corr(A,B,C, dist<=300)
                if sr is not None and sr>best[0]: best=(sr,A,B,C)
    improved = (sr0 is not None) and (best[0] - sr0 >= 0.05)
    if improved and "--write" in sys.argv:
        CALIB.write_text(json.dumps({"A":best[1],"B":best[2],"C":best[3],
            "note":f"実測較正 Spearman {sr0:.3f}->{best[0]:.3f}"}, ensure_ascii=False), encoding="utf-8")
        print(f"[calib] 改善あり→採用 (A,B,C)=({best[1]},{best[2]},{best[3]}) 書出: {CALIB.name}", flush=True)
    elif improved:
        print(f"[calib] 改善あり(未書出。--write で採用): (A,B,C)=({best[1]},{best[2]},{best[3]})", flush=True)
    else:
        print(f"[calib] 有意な改善なし(+0.05未満)→係数は既定(1.0,0.5,1.0)のまま", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "ab"
    if mode in ("a", "ab"): stage_a()
    if mode in ("b", "ab"): stage_b()
    if mode == "calib": calib()
