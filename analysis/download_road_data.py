"""
サブステップ12-2: 幹線道路データ取得（Overpass API）

OpenStreetMap から国道(highway=trunk)・主要地方道(highway=primary)を取得。
Wayのジオメトリを含めて取得し、GeoJSONに変換。

出力: analysis/geo_data/roads_kanto.geojson
"""
import json
import logging
import time
import urllib.parse
import urllib.request
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent
GEO_DATA = BASE_DIR / "geo_data"
GEO_DATA.mkdir(exist_ok=True)
LOG_PATH = BASE_DIR / "progress.log"
OUT_PATH = GEO_DATA / "roads_kanto.geojson"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
    "https://overpass.openstreetmap.fr/oapi/interpreter",
    "https://overpass-api.de/api/interpreter",
]

# 道路クエリ: trunk(国道) + primary(主要地方道) だが重いので trunk のみに絞る
# → 後で近接スコア計算に使う。地図表示にも十分な密度。
ROAD_FILTER = '"highway"="trunk"'

# bbox を細かく分割（重いクエリ対策）
PREF_BBOXES = {
    "東京都":    ["35.50,138.95,35.90,139.93"],
    "神奈川県":  ["35.12,138.93,35.70,139.78"],
    "埼玉県南":  ["35.74,138.72,36.02,139.95"],  # 南北に2分割
    "埼玉県北":  ["36.02,138.72,36.30,139.95"],
    "千葉県西":  ["35.18,139.72,35.95,140.30"],  # 東西に2分割
    "千葉県東":  ["35.18,140.30,35.95,140.90"],
}


def _urllib_post(url: str, query: str, timeout_sec: int) -> dict:
    """urllib で POST（requests より互換性が高い）"""
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "*/*")
    req.add_header("User-Agent", "daikichi-mapper/1.0")
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        return json.loads(resp.read())


def overpass_query(query: str, timeout_sec: int = 90) -> dict:
    """全 Overpass サーバーで試す（urllib POST 優先）"""
    attempts = [
        ("urllib_post", "https://overpass-api.de/api/interpreter"),
        ("GET",         "https://overpass.kumi.systems/api/interpreter"),
        ("POST",        "https://overpass.kumi.systems/api/interpreter"),
        ("urllib_post", "https://overpass.kumi.systems/api/interpreter"),
    ]
    for method, url in attempts:
        try:
            if method == "urllib_post":
                return _urllib_post(url, query, timeout_sec + 30)
            elif method == "GET":
                r = requests.get(url, params={"data": query},
                                 headers={"Accept": "application/json"},
                                 timeout=timeout_sec + 30)
                if r.status_code == 200:
                    return r.json()
                log.warning(f"  {method} {url}: {r.status_code}")
            else:
                r = requests.post(url, data={"data": query},
                                  headers={"Accept": "application/json"},
                                  timeout=timeout_sec + 30)
                if r.status_code == 200:
                    return r.json()
                log.warning(f"  {method} {url}: {r.status_code}")
        except Exception as e:
            log.warning(f"  {method} {url}: {type(e).__name__}: {str(e)[:60]}")
        time.sleep(2)
    raise RuntimeError("全 Overpass サーバーで失敗")


def fetch_roads_area(area_key: str, bbox: str) -> list[dict]:
    """1エリア分の国道 Way を取得"""
    cache_path = GEO_DATA / f"roads_{area_key}.json"
    if cache_path.exists():
        log.info(f"  [{area_key}] キャッシュ読込 ({cache_path.stat().st_size//1024}KB)")
        return json.loads(cache_path.read_text(encoding="utf-8"))

    query = (
        f'[out:json][timeout:60];'
        f'way[{ROAD_FILTER}]({bbox});'
        f'out geom qt;'
    )
    log.info(f"  [{area_key}] クエリ送信: {bbox}")
    data = overpass_query(query, timeout_sec=90)
    elements = data.get("elements", [])
    cache_path.write_text(json.dumps(elements), encoding="utf-8")
    log.info(f"    {len(elements)} way ({cache_path.stat().st_size//1024}KB)")
    return elements


def ways_to_geojson(all_ways: list[dict]) -> dict:
    """Overpass Way → GeoJSON LineString"""
    features = []
    seen_ids = set()
    for way in all_ways:
        if way.get("type") != "way":
            continue
        wid = way.get("id")
        if wid in seen_ids:
            continue
        seen_ids.add(wid)

        geometry = way.get("geometry", [])
        if len(geometry) < 2:
            continue

        coords = [[pt["lon"], pt["lat"]] for pt in geometry]
        tags = way.get("tags", {})
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "osm_id":   wid,
                "highway":  tags.get("highway", ""),
                "name":     tags.get("name") or tags.get("ref", ""),
                "ref":      tags.get("ref", ""),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def simplify_geojson(gj: dict, tolerance: float = 0.0005) -> dict:
    """座標を簡略化してファイルサイズを削減"""
    try:
        import geopandas as gpd
        from shapely.geometry import shape, mapping
        import pandas as pd

        gdf = gpd.GeoDataFrame.from_features(gj["features"], crs="EPSG:4326")
        before = len(gdf)
        gdf["geometry"] = gdf["geometry"].simplify(tolerance, preserve_topology=True)
        gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
        log.info(f"  簡略化: {before} → {len(gdf)} way")
        # GeoJSON に戻す
        return json.loads(gdf.to_json())
    except Exception as e:
        log.warning(f"  簡略化スキップ: {e}")
        return gj


def main():
    log.info("=== 12-2: 幹線道路データ取得 ===")

    all_ways: list[dict] = []
    for area_key, bboxes in PREF_BBOXES.items():
        for bbox in bboxes:
            ways = fetch_roads_area(area_key, bbox)
            all_ways.extend(ways)
            time.sleep(2)

    log.info(f"  合計 {len(all_ways)} way（重複含む）")

    log.info("[2] GeoJSON 変換")
    gj = ways_to_geojson(all_ways)
    log.info(f"  {len(gj['features'])} LineString（重複除去後）")

    log.info("[3] 座標簡略化")
    gj = simplify_geojson(gj)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(gj, f, ensure_ascii=False, separators=(",", ":"))

    kb = OUT_PATH.stat().st_size // 1024
    log.info(f"  保存: {OUT_PATH.name} ({kb}KB, {len(gj['features'])} way)")
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
