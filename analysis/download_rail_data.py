"""
サブステップ12-1: 鉄道駅データ取得（Overpass API）

OpenStreetMap Overpass API から関東4都県の鉄道駅を取得。
railway=station のノードを bbox でフィルタ。

出力: analysis/geo_data/stations_kanto.geojson
"""
import json
import logging
import time
from pathlib import Path

import requests

BASE_DIR  = Path(__file__).parent
GEO_DATA  = BASE_DIR / "geo_data"
GEO_DATA.mkdir(exist_ok=True)
LOG_PATH  = BASE_DIR / "progress.log"
OUT_PATH  = GEO_DATA / "stations_kanto.geojson"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

# 都県ごとに分割（タイムアウト回避）
PREF_BBOXES = {
    "東京都":   "35.50,138.95,35.90,139.93",
    "神奈川県": "35.12,138.93,35.70,139.78",
    "埼玉県":   "35.74,138.72,36.30,139.95",
    "千葉県":   "35.18,139.72,35.95,140.90",
    "茨城県":   "35.73,139.66,36.95,140.88",
    "栃木県":   "36.18,139.32,37.16,140.30",
    "群馬県":   "35.98,138.40,37.06,139.67",
    "静岡県":   "34.57,137.45,35.66,139.18",
}


def _urllib_post(url: str, query: str, timeout_sec: int) -> list[dict]:
    """urllib POST（overpass-api.de は requests POST だと406になるため）"""
    import urllib.parse, urllib.request, json as _json
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", "daikichi-mapper/1.0")
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        return _json.loads(resp.read()).get("elements", [])


def overpass_query(query: str, timeout_sec: int = 120) -> list[dict]:
    """複数サーバー・GET/POST/urllib を試しながら Overpass クエリを実行"""
    attempts = [
        ("urllib", "https://overpass-api.de/api/interpreter"),
        ("GET",    OVERPASS_URLS[0]),
        ("POST",   OVERPASS_URLS[0]),
        ("urllib", OVERPASS_URLS[0]),
    ]
    for method, url in attempts:
        try:
            if method == "urllib":
                return _urllib_post(url, query, timeout_sec + 30)
            elif method == "GET":
                r = requests.get(url, params={"data": query},
                                 headers={"Accept": "application/json"},
                                 timeout=timeout_sec + 30)
            else:
                r = requests.post(url, data={"data": query},
                                  headers={"Accept": "application/json"},
                                  timeout=timeout_sec + 30)
            if method != "urllib" and r.status_code == 200:
                return r.json().get("elements", [])
            if method != "urllib":
                log.warning(f"  {method} {url}: {r.status_code}")
        except Exception as e:
            log.warning(f"  {method} {url}: {type(e).__name__}")
        time.sleep(3)
    raise RuntimeError("全 Overpass サーバーで失敗")


def fetch_stations() -> list[dict]:
    """都県ごとに Overpass API で鉄道駅ノードを取得（中間保存あり）"""
    all_elements = []
    seen_ids = set()
    for pref, bbox in PREF_BBOXES.items():
        # 都県ごとのキャッシュファイル
        cache_path = GEO_DATA / f"stations_{pref}.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            new = [e for e in cached if e.get("id") not in seen_ids]
            seen_ids.update(e.get("id") for e in new)
            all_elements.extend(new)
            log.info(f"  [{pref}] キャッシュ読込: {len(new)} 駅")
            continue

        query = f'[out:json][timeout:60];node["railway"="station"]({bbox});out body qt;'
        log.info(f"  [{pref}] bbox={bbox}")
        elements = overpass_query(query, timeout_sec=90)
        cache_path.write_text(json.dumps(elements), encoding="utf-8")

        new = [e for e in elements if e.get("id") not in seen_ids]
        seen_ids.update(e.get("id") for e in new)
        all_elements.extend(new)
        log.info(f"    {len(new)} 駅（累計 {len(all_elements)}）")
        time.sleep(3)
    return all_elements


def to_geojson(elements: list[dict]) -> dict:
    features = []
    for el in elements:
        if el.get("type") != "node":
            continue
        lat, lon = el.get("lat"), el.get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags", {})
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "osm_id":      el.get("id"),
                "name":        tags.get("name") or tags.get("name:ja", ""),
                "operator":    tags.get("operator", ""),
                "railway":     tags.get("railway", "station"),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def main():
    log.info("=== 12-1: 鉄道駅データ取得 ===")

    if OUT_PATH.exists():
        log.info(f"  スキップ（既存 {OUT_PATH.stat().st_size//1024}KB）")
        return

    elements = fetch_stations()
    gj = to_geojson(elements)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(gj, f, ensure_ascii=False, separators=(",", ":"))

    n = len(gj["features"])
    kb = OUT_PATH.stat().st_size // 1024
    log.info(f"  保存: {OUT_PATH.name} ({kb}KB, {n}駅)")

    # サンプル表示
    for feat in gj["features"][:5]:
        p = feat["properties"]
        c = feat["geometry"]["coordinates"]
        log.info(f"    {p['name']} ({p['operator']}) lat={c[1]:.4f} lon={c[0]:.4f}")

    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
