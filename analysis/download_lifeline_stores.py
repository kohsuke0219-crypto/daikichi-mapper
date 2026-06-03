"""
生活動線レイヤー: 大手食品スーパー・複合商業施設の店舗取得

データソース: OpenStreetMap Overpass API (shop=supermarket / shop=mall /
              shop=department_store)  取得日: 2026-05-29
対象: 東京都・神奈川県・埼玉県・千葉県の1都3県

対象チェーン(反復来店型・生活密着型に限定):
  食品スーパー: サミット/コープ/いなげや/西友/オーケー/ライフ/マルエツ/
               ヤオコー/東急ストア/東武ストア/イトーヨーカドー/ベルク/カスミ
  複合施設    : イオンモール/イオン/アリオ/ららぽーと/グランベリーパーク

判定: 店名(name/brand/operator)を下記パターンで照合。マッチしたチェーンの
      カテゴリ(スーパー/複合施設)を付与。非該当は除外(件数のみ報告)。

出力: docs/data/lifeline_stores.json
  [{name, category, chain, prefecture, lat, lng}]
"""
import json
import logging
import time
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd

BASE_DIR  = Path(__file__).parent
DOCS_DATA = BASE_DIR.parent / "docs" / "data"
GEO_DATA  = BASE_DIR / "geo_data"
GEO_DATA.mkdir(exist_ok=True)
LOG_PATH  = BASE_DIR / "progress.log"
OUT_PATH  = DOCS_DATA / "lifeline_stores.json"
WARD_GEOJSON = DOCS_DATA / "ward_population.geojson"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# 都県別 bbox (南緯,西経,北緯,東経) ※若干広めに取り後でポリゴンで厳密判定
PREF_BBOXES = {
    "東京都":   "35.50,138.93,35.90,139.93",
    "神奈川県": "35.12,138.90,35.70,139.80",
    "埼玉県":   "35.74,138.70,36.30,139.96",
    "千葉県":   "35.15,139.70,36.10,140.92",
    "茨城県":   "35.73,139.66,36.95,140.88",
    "栃木県":   "36.18,139.32,37.16,140.30",
    "群馬県":   "35.98,138.40,37.06,139.67",
    "静岡県":   "34.57,137.45,35.66,139.18",
}

# (パターン[小文字], チェーン名, カテゴリ)  ※先頭からの最初一致を採用
CHAIN_PATTERNS = [
    # ---- 複合施設 ----
    ("イオンモール", "イオンモール", "複合施設"),
    ("aeon mall",    "イオンモール", "複合施設"),
    ("aeonmall",     "イオンモール", "複合施設"),
    ("イオンタウン", "イオンタウン", "複合施設"),
    ("イオンスタイル","イオンスタイル","複合施設"),
    ("イオン",       "イオン",       "複合施設"),
    ("aeon",         "イオン",       "複合施設"),
    ("ジャスコ",     "イオン",       "複合施設"),
    ("アリオ",       "アリオ",       "複合施設"),
    ("ario",         "アリオ",       "複合施設"),
    ("ららぽーと",   "ららぽーと",   "複合施設"),
    ("lalaport",     "ららぽーと",   "複合施設"),
    ("グランベリー", "グランベリーパーク", "複合施設"),
    ("grandberry",   "グランベリーパーク", "複合施設"),
    # ---- 食品スーパー ----
    ("サミット",     "サミット",     "スーパー"),
    ("summit store", "サミット",     "スーパー"),
    ("いなげや",     "いなげや",     "スーパー"),
    ("inageya",      "いなげや",     "スーパー"),
    ("西友",         "西友",         "スーパー"),
    ("seiyu",        "西友",         "スーパー"),
    ("オーケー",     "オーケー",     "スーパー"),
    ("ok store",     "オーケー",     "スーパー"),
    ("okストア",     "オーケー",     "スーパー"),
    ("ライフ",       "ライフ",       "スーパー"),
    ("マルエツ",     "マルエツ",     "スーパー"),
    ("maruetsu",     "マルエツ",     "スーパー"),
    ("ヤオコー",     "ヤオコー",     "スーパー"),
    ("yaoko",        "ヤオコー",     "スーパー"),
    ("東急ストア",   "東急ストア",   "スーパー"),
    ("プレッセ",     "東急ストア",   "スーパー"),
    ("tokyu store",  "東急ストア",   "スーパー"),
    ("東武ストア",   "東武ストア",   "スーパー"),
    ("tobu store",   "東武ストア",   "スーパー"),
    ("イトーヨーカ", "イトーヨーカドー", "スーパー"),
    ("ヨーカドー",   "イトーヨーカドー", "スーパー"),
    ("ito-yokado",   "イトーヨーカドー", "スーパー"),
    ("ベルク",       "ベルク",       "スーパー"),
    ("belc",         "ベルク",       "スーパー"),
    ("カスミ",       "カスミ",       "スーパー"),
    ("kasumi",       "カスミ",       "スーパー"),
    ("フードスクエア","カスミ",       "スーパー"),
    ("コープみらい", "コープみらい", "スーパー"),
    ("ユーコープ",   "ユーコープ",   "スーパー"),
    ("コープ",       "コープ",       "スーパー"),
    ("coop",         "コープ",       "スーパー"),
    ("co-op",        "コープ",       "スーパー"),
    ("生協",         "コープ",       "スーパー"),
    # ---- 地場・ロードサイド系スーパー（北関東・茨城・静岡ほか「田舎スーパー」）----
    ("ベイシア",       "ベイシア",       "スーパー"),
    ("beisia",         "ベイシア",       "スーパー"),
    ("とりせん",       "とりせん",       "スーパー"),
    ("torisen",        "とりせん",       "スーパー"),
    ("フレッセイ",     "フレッセイ",     "スーパー"),
    ("fressay",        "フレッセイ",     "スーパー"),
    ("たいらや",       "たいらや",       "スーパー"),
    ("オータニ",       "オータニ",       "スーパー"),
    ("かましん",       "かましん",       "スーパー"),
    ("kamashin",       "かましん",       "スーパー"),
    ("ヨークベニマル", "ヨークベニマル", "スーパー"),
    ("ベニマル",       "ヨークベニマル", "スーパー"),
    ("york benimaru",  "ヨークベニマル", "スーパー"),
    ("ヨークマート",   "ヨークマート",   "スーパー"),
    ("ザ・ビッグ",     "ザ・ビッグ",     "スーパー"),
    ("ザ ビッグ",      "ザ・ビッグ",     "スーパー"),
    ("ザビッグ",       "ザ・ビッグ",     "スーパー"),
    ("the big",        "ザ・ビッグ",     "スーパー"),
    ("マックスバリュ", "マックスバリュ", "スーパー"),
    ("maxvalu",        "マックスバリュ", "スーパー"),
    ("max valu",       "マックスバリュ", "スーパー"),
    ("バロー",         "バロー",         "スーパー"),
    ("valor",          "バロー",         "スーパー"),
    ("マルト",         "マルト",         "スーパー"),
    ("セイミヤ",       "セイミヤ",       "スーパー"),
    ("タイヨー",       "タイヨー",       "スーパー"),
    ("ランドローム",   "ランドローム",   "スーパー"),
    # 静岡の地場スーパー
    ("田子重",         "田子重",         "スーパー"),
    ("しずてつ",       "しずてつストア", "スーパー"),
    ("静鉄",           "しずてつストア", "スーパー"),
    ("遠鉄",           "遠鉄ストア",     "スーパー"),
    ("富士シティオ",   "富士シティオ",   "スーパー"),
    ("富士ガーデン",   "富士ガーデン",   "スーパー"),
    ("杏林堂",         "杏林堂",         "スーパー"),
    ("アオキ",         "アオキ",         "スーパー"),
    # GMS（複合施設扱い）
    ("アピタ",         "アピタ",         "複合施設"),
    ("apita",          "アピタ",         "複合施設"),
    ("ピアゴ",         "ピアゴ",         "複合施設"),
    ("piago",          "ピアゴ",         "複合施設"),
    ("ユニー",         "ユニー",         "複合施設"),
]

# アウトレット等(非日常・低頻度)は除外
EXCLUDE_KEYWORDS = ["アウトレット", "outlet"]

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


def overpass(query: str, timeout_sec: int = 120):
    """urllib POST 優先で Overpass を叩く"""
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last = None
    for url in OVERPASS_URLS:
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            req.add_header("User-Agent", "daikichi-mapper/1.0")
            with urllib.request.urlopen(req, timeout=timeout_sec + 30) as resp:
                return json.loads(resp.read())
        except Exception as e:
            last = e
            log.warning(f"  {url}: {type(e).__name__}")
            time.sleep(3)
    raise RuntimeError(f"Overpass全滅: {last}")


def classify(name: str):
    """店名からチェーン・カテゴリを判定。非該当は (None,None)"""
    low = name.lower()
    if any(k in low for k in EXCLUDE_KEYWORDS):
        return None, None
    for pat, chain, cat in CHAIN_PATTERNS:
        if pat.lower() in low:
            return chain, cat
    return None, None


def fetch_pref(pref: str, bbox: str) -> list[dict]:
    """1都県分のスーパー・モールを取得(キャッシュあり)"""
    cache = GEO_DATA / f"lifeline_{pref}.json"
    if cache.exists():
        log.info(f"  [{pref}] キャッシュ ({cache.stat().st_size//1024}KB)")
        return json.loads(cache.read_text(encoding="utf-8"))

    query = (
        f'[out:json][timeout:120];('
        f'node["shop"="supermarket"]({bbox});'
        f'way["shop"="supermarket"]({bbox});'
        f'node["shop"="mall"]({bbox});'
        f'way["shop"="mall"]({bbox});'
        f'node["shop"="department_store"]({bbox});'
        f'way["shop"="department_store"]({bbox});'
        f');out center tags;'
    )
    log.info(f"  [{pref}] Overpass取得: {bbox}")
    data = overpass(query)
    els = data.get("elements", [])
    cache.write_text(json.dumps(els), encoding="utf-8")
    log.info(f"    {len(els)} 施設(生)")
    return els


def main():
    log.info("=== 生活動線(スーパー・複合施設)取得 ===")

    # ---- Overpass取得 ----
    raw = []
    for pref, bbox in PREF_BBOXES.items():
        raw.extend(fetch_pref(pref, bbox))
        time.sleep(2)
    log.info(f"  生施設総数: {len(raw)}")

    # ---- 分類 & 座標抽出 ----
    rows = []
    seen_ids = set()
    excluded = 0
    for el in raw:
        oid = (el.get("type"), el.get("id"))
        if oid in seen_ids:
            continue
        seen_ids.add(oid)
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("brand") or tags.get("operator") or ""
        if not name:
            excluded += 1
            continue
        # 座標(node=lat/lon, way=center)
        if el.get("type") == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            c = el.get("center", {})
            lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            excluded += 1
            continue
        # 照合(name/brand/operator のいずれかでヒットすればよい)
        chain = cat = None
        for cand in [tags.get("name",""), tags.get("brand",""), tags.get("operator","")]:
            if cand:
                chain, cat = classify(cand)
                if chain:
                    break
        if not chain:
            excluded += 1
            continue
        rows.append({
            "name": name, "category": cat, "chain": chain,
            "lat": float(lat), "lng": float(lon),
        })

    log.info(f"  対象チェーン該当: {len(rows)} / 除外(非該当・無名・無座標): {excluded}")

    # ---- 座標による名寄せ(同一店が複数ソースで重複: 約120m以内+同チェーンを排除) ----
    rows.sort(key=lambda r: (r["chain"], r["lat"], r["lng"]))
    deduped = []
    for r in rows:
        dup = False
        for d in deduped:
            if d["chain"] == r["chain"] and \
               abs(d["lat"]-r["lat"]) < 0.0011 and abs(d["lng"]-r["lng"]) < 0.0011:
                dup = True
                break
        if not dup:
            deduped.append(r)
    log.info(f"  名寄せ後: {len(deduped)} (重複 {len(rows)-len(deduped)} 排除)")

    # ---- 都県をポリゴンで厳密判定(1都3県外を除外) ----
    log.info("  市区町村ポリゴンで都県判定")
    wards = gpd.read_file(WARD_GEOJSON)[["pref", "geometry"]]
    pts = gpd.GeoDataFrame(
        deduped,
        geometry=gpd.points_from_xy([r["lng"] for r in deduped],
                                    [r["lat"] for r in deduped]),
        crs="EPSG:4326",
    )
    joined = gpd.sjoin(pts, wards, how="left", predicate="within")
    joined = joined.drop_duplicates(subset=["name", "lat", "lng"])

    # N03の都道府県名ゆれを正規化(例: "神奈川" → "神奈川県")
    PREF_NORMALIZE = {"神奈川": "神奈川県", "東京": "東京都",
                      "埼玉": "埼玉県", "千葉": "千葉県", "茨城": "茨城県",
                      "栃木": "栃木県", "群馬": "群馬県", "静岡": "静岡県"}

    final = []
    target_prefs = set(PREF_BBOXES.keys())
    outside = 0
    for _, r in joined.iterrows():
        pref = r.get("pref")
        if pd.notna(pref):
            pref = PREF_NORMALIZE.get(pref, pref)
        if pd.isna(pref) or pref not in target_prefs:
            outside += 1
            continue
        final.append({
            "name": r["name"], "category": r["category"], "chain": r["chain"],
            "prefecture": pref, "lat": round(r["lat"], 6), "lng": round(r["lng"], 6),
        })
    log.info(f"  1都3県内: {len(final)} (圏外除外 {outside})")

    OUT_PATH.write_text(json.dumps(final, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    log.info(f"  保存: {OUT_PATH.name} ({OUT_PATH.stat().st_size//1024}KB)")

    # ---- 集計報告 ----
    df = pd.DataFrame(final)
    log.info("=== 業態別×都県別 集計 ===")
    pivot = df.pivot_table(index="prefecture", columns="category",
                           values="name", aggfunc="count", fill_value=0)
    log.info("\n" + pivot.to_string())
    log.info("=== チェーン別 上位 ===")
    log.info("\n" + df["chain"].value_counts().to_string())

    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
