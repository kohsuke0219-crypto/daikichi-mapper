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


def stage_b():
    import scipy.spatial as sp
    print("[B] 読込", flush=True)
    roads = gpd.read_parquet(ROADS_PQ).to_crs(4326)
    pois = gpd.read_parquet(POIS_PQ).to_crs(4326)
    flow = json.loads(FLOW.read_text(encoding="utf-8"))
    st = json.loads(STATIONS.read_text(encoding="utf-8"))
    wards = gpd.read_file(WARD)[["pref", "geometry"]]

    # 代表点(midpoint)
    roads = roads[roads.geometry.notna() & (roads.geometry.geom_type == "LineString")].copy()
    mid = roads.geometry.interpolate(0.5, normalized=True)
    roads["lng"] = mid.x; roads["lat"] = mid.y

    # 3府県内に絞る（midpointを県ポリゴンにsjoin）
    mp = gpd.GeoDataFrame(roads.drop(columns="geometry"), geometry=mid, crs=4326)
    j = gpd.sjoin(mp, wards, how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")]
    prefn = {"神奈川": "神奈川県"}
    j["pref"] = j["pref"].map(lambda x: prefn.get(x, x))
    roads = roads.loc[j["pref"].isin({"東京都", "神奈川県", "埼玉県"}).values].copy()
    roads["lng"] = mid.loc[roads.index].x; roads["lat"] = mid.loc[roads.index].y
    print(f"    3府県内 道路区間: {len(roads)}", flush=True)

    # メートル座標で沿道店舗数(50m)・駅近接
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
    # 駅近接（EPSG:6677で最近傍駅の距離＋乗降客数）
    sxy = []; sride = []
    for s in st:
        if s.get("lat") and s.get("lng"):
            sxy.append((s["lng"], s["lat"])); sride.append(s.get("total", 0) or 0)
    sgdf = gpd.GeoDataFrame(geometry=gpd.points_from_xy([a[0] for a in sxy], [a[1] for a in sxy]), crs=4326).to_crs(METRIC)
    smat = np.c_[sgdf.geometry.x.values, sgdf.geometry.y.values]
    stree = sp.cKDTree(smat)
    dist, idx = stree.query(rx, k=1)
    dist_km = dist / 1000.0
    ride = np.array(sride)[idx]
    st_factor = (1 + np.log10(1 + ride) / 3.0) * np.exp(-dist_km / 0.8)

    clsW = roads["highway"].map(CLASS_W).fillna(0.4).values
    weight = clsW * (1 + 0.5 * shops) * (0.4 + st_factor)
    roads["w"] = weight; roads["shops"] = shops
    roads["st_km"] = np.round(dist_km, 2)

    # メッシュ割当
    m8 = []; m6 = []
    for la, lo in zip(roads["lat"].values, roads["lng"].values):
        a, b = mesh_codes(la, lo); m8.append(a); m6.append(b)
    roads["m8"] = m8; roads["m6"] = m6

    # メッシュ内で wd_day を weight 比例配分 → 人流指数
    wsum = roads.groupby("m8")["w"].transform("sum")
    wd = roads["m8"].map(lambda m: (flow.get(m, {}) or {}).get("wd_day", 0)).astype(float)
    roads["idx"] = np.where(wsum > 0, wd * roads["w"] / wsum, 0.0)
    roads = roads[roads["idx"] > 0].copy()
    roads["idx"] = roads["idx"].round().astype(int)
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


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "ab"
    if mode in ("a", "ab"): stage_a()
    if mode in ("b", "ab"): stage_b()
