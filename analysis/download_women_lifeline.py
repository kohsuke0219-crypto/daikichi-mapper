"""
機能2（女性向け生活動線施設レイヤー）用:
40歳以上女性が頻繁に通う5チェーンの店舗座標を OpenStreetMap Overpass API から取得する。

対象チェーン（これ以外は追加しない）:
  - カーブス (Curves)            … フィットネス
  - ホットヨガ LAVA (ラバ)        … ホットヨガ
  - ホットヨガ カルド (CALDO)     … ホットヨガ
  - ユザワヤ                      … 手芸・生活雑貨
  - クラフトハートトーカイ(トーカイ) … 手芸

対象エリア: 東京都・神奈川県・埼玉県・千葉県（既存マップの一部と同じ1都3県）
データ取得元: OpenStreetMap Overpass API
取得日: 2026-06-04
名寄せ: osm種別(node/way/relation)+id で重複除去、さらに (chain, 緯度経度小数4桁) で重複除去

出力: docs/data/women_lifeline_stores.json
      [ {name, chain, prefecture, lat, lng, osm_type, osm_id}, ... ]

※ OSMは網羅性が完全でない（特にLAVA/カルド/トーカイは未登録店あり）。
   実数は各社公式店舗一覧より少ない可能性 → TODO: 公式店舗一覧での補完。
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
OUT_PATH = BASE_DIR.parent / "docs" / "data" / "women_lifeline_stores.json"

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

# 対象エリア bbox（既存マップと同じ範囲に愛知・山梨を追加）
PREF_BBOXES = {
    "東京都":   "35.50,138.95,35.90,139.93",
    "神奈川県": "35.12,138.93,35.70,139.78",
    "埼玉県":   "35.74,138.72,36.30,139.95",
    "千葉県":   "35.18,139.72,35.95,140.90",
    "愛知県":   "34.57,136.66,35.43,137.84",
    "山梨県":   "35.17,138.18,35.98,139.16",
    "長野県":   "35.20,137.32,37.03,138.75",
}

# チェーン定義: key=チェーン表示名, regex=OSM name正規表現(大小無視)
CHAINS = {
    "カーブス":   r"カーブス|Curves",
    "LAVA":       r"ホットヨガ.*LAVA|LAVA.*ホットヨガ|スタジオ.*LAVA|LAVA",
    "カルド":     r"カルド|CALDO",
    "ユザワヤ":   r"ユザワヤ|Yuzawaya",
    "トーカイ":   r"クラフトハート|手芸センタートーカイ|手芸.*トーカイ|トーカイ",
}

# トーカイの素の「トーカイ」マッチを採用する条件に使う shopタグ（誤検出抑制）
CRAFT_SHOPS = {"craft", "fabric", "variety_store", "doityourself", "department_store", "houseware"}


def _urllib_post(url: str, query: str, timeout_sec: int) -> list[dict]:
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", "daikichi-mapper/1.0")
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        return json.loads(resp.read()).get("elements", [])


def overpass_query(query: str, timeout_sec: int = 120) -> list[dict]:
    attempts = [
        ("urllib", "https://overpass-api.de/api/interpreter"),
        ("GET",    OVERPASS_URLS[0]),
        ("urllib", OVERPASS_URLS[0]),
    ]
    last_err = None
    for method, url in attempts:
        try:
            if method == "urllib":
                return _urllib_post(url, query, timeout_sec + 30)
            r = requests.get(url, params={"data": query},
                             headers={"Accept": "application/json"},
                             timeout=timeout_sec + 30)
            if r.status_code == 200:
                return r.json().get("elements", [])
            log.warning(f"  {method} {url}: {r.status_code}")
        except Exception as e:
            last_err = e
            log.warning(f"  {method} {url}: {type(e).__name__}")
        time.sleep(3)
    raise RuntimeError(f"全 Overpass サーバーで失敗: {last_err}")


def classify(name: str, tags: dict) -> str | None:
    """店名(+タグ)からチェーンを判定。該当なしは None。"""
    import re
    n = name or ""
    for chain, pat in CHAINS.items():
        if not re.search(pat, n, re.IGNORECASE):
            continue
        if chain == "トーカイ":
            # クラフトハート/手芸 を含めば確定。素の「トーカイ」のみは craft系shopタグを要求
            if re.search(r"クラフトハート|手芸", n):
                return chain
            shop = (tags.get("shop") or "").lower()
            if shop in CRAFT_SHOPS:
                return chain
            continue  # 誤検出(東海系など)を除外
        if chain == "LAVA":
            # 「LAVA」のみは誤検出が多い→ヨガ/ホットヨガ文脈 or fitnessタグを要求
            if re.search(r"ホットヨガ|ヨガ|yoga", n, re.IGNORECASE):
                return chain
            leisure = (tags.get("leisure") or "").lower()
            sport = (tags.get("sport") or "").lower()
            if leisure == "fitness_centre" or "yoga" in sport:
                return chain
            continue
        return chain
    return None


def fetch_pref(pref: str, bbox: str) -> list[dict]:
    cache = GEO_DATA / f"women_lifeline_{pref}.json"
    if cache.exists():
        log.info(f"  [{pref}] キャッシュ読込")
        return json.loads(cache.read_text(encoding="utf-8"))

    # 全チェーンの name 候補を1クエリにまとめて node/way/relation を取得
    name_union = "|".join(p for p in CHAINS.values())
    query = (
        f'[out:json][timeout:120];'
        f'nwr["name"~"{name_union}",i]({bbox});'
        f'out center tags;'
    )
    log.info(f"  [{pref}] bbox={bbox}")
    elements = overpass_query(query, timeout_sec=120)
    cache.write_text(json.dumps(elements, ensure_ascii=False), encoding="utf-8")
    log.info(f"    raw {len(elements)} 要素")
    time.sleep(3)
    return elements


def main():
    log.info("=== 女性向け生活動線施設 取得 ===")
    seen_osm = set()       # (type,id)
    seen_geo = set()       # (chain, round(lat,4), round(lng,4))
    out = []
    per_chain = {c: 0 for c in CHAINS}

    for pref, bbox in PREF_BBOXES.items():
        elements = fetch_pref(pref, bbox)
        for el in elements:
            otype, oid = el.get("type"), el.get("id")
            if (otype, oid) in seen_osm:
                continue
            tags = el.get("tags", {})
            name = tags.get("name") or tags.get("name:ja") or tags.get("brand") or ""
            chain = classify(name, tags)
            if not chain:
                continue
            # 座標（way/relation は center）
            if otype == "node":
                lat, lng = el.get("lat"), el.get("lon")
            else:
                c = el.get("center", {})
                lat, lng = c.get("lat"), c.get("lon")
            if lat is None or lng is None:
                continue
            gkey = (chain, round(lat, 4), round(lng, 4))
            if gkey in seen_geo:
                continue
            seen_osm.add((otype, oid))
            seen_geo.add(gkey)
            out.append({
                "name": name or chain,
                "chain": chain,
                "prefecture": pref,
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "osm_type": otype,
                "osm_id": oid,
            })
            per_chain[chain] += 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    log.info(f"  保存: {OUT_PATH.name} 計{len(out)}件")
    for c, n in per_chain.items():
        log.info(f"    {c}: {n}件")
    # 都県別
    by_pref = {}
    for s in out:
        by_pref[s["prefecture"]] = by_pref.get(s["prefecture"], 0) + 1
    for p, n in by_pref.items():
        log.info(f"    {p}: {n}件")
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
