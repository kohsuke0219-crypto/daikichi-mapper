"""
[フェーズ12 補正] 市区町村境界の正しい再構築

問題: 既存 ward_population.geojson は build_geojson.py が
「コードごとに最初のポリゴンだけ採用」したため、各市区町村が
1断片に切り詰められていた（港区が0.0002km²など）。
→ 面積・駅密度・空間結合がすべて不正。

修正: N03 を再ダウンロードし、5桁コードごとに全ポリゴンを dissolve。
人口データは既存geojsonのproperties（人口値は正しい）から引き継ぐ。

出力:
  docs/data/ward_population.geojson  （上書き：正しい境界）
  analysis/ward_area.csv             （code, city, area_km2）
"""
import io
import json
import logging
import time
import zipfile
from pathlib import Path

import requests
import geopandas as gpd
import pandas as pd

BASE_DIR  = Path(__file__).parent
DOCS_DATA = BASE_DIR.parent / "docs" / "data"
LOG_PATH  = BASE_DIR / "progress.log"
GEO_DATA  = BASE_DIR / "geo_data"
GEO_DATA.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

MLIT_BASE = "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2023/N03-20230101_{pref_code}_GML.zip"
PREF_CODES = {"東京都": "13", "神奈川県": "14", "埼玉県": "11", "千葉県": "12", "茨城県": "08",
              "栃木県": "09", "群馬県": "10", "静岡県": "22", "愛知県": "23", "山梨県": "19",
              "長野県": "20"}

WARD_GEOJSON = DOCS_DATA / "ward_population.geojson"
AREA_CSV     = BASE_DIR / "ward_area.csv"
METRIC_CRS   = "EPSG:6677"

# 簡略化トレランス（度）。0.0003 ≒ 約33m。境界形状を保ちつつ軽量化。
SIMPLIFY_TOL = 0.0003


def load_existing_population() -> dict:
    """既存 geojson から code→人口 を抽出（人口値は正しい）"""
    with open(WARD_GEOJSON, encoding="utf-8") as f:
        data = json.load(f)
    pop = {}
    for feat in data["features"]:
        p = feat.get("properties", {})
        code = str(p.get("code", "")).zfill(5)
        if code and code not in pop:
            pop[code] = {
                "total_pop":    p.get("total_pop", 0),
                "women_40plus": p.get("women_40plus", 0),
                "women_total":  p.get("women_total", 0),
            }
    log.info(f"  既存人口データ: {len(pop)} 市区町村")
    return pop


def fetch_pref_gdf(pref_name: str, pref_code: str) -> gpd.GeoDataFrame:
    """1都県分の N03 を取得し GeoDataFrame で返す（キャッシュあり）"""
    cache = GEO_DATA / f"N03_{pref_code}.zip"
    if cache.exists() and cache.stat().st_size > 100_000:
        log.info(f"  [{pref_name}] キャッシュ ({cache.stat().st_size//1024}KB)")
        zip_bytes = cache.read_bytes()
    else:
        url = MLIT_BASE.format(pref_code=pref_code)
        log.info(f"  [{pref_name}] ダウンロード: {url}")
        r = requests.get(url, timeout=180)
        r.raise_for_status()
        zip_bytes = r.content
        cache.write_bytes(zip_bytes)
        log.info(f"  [{pref_name}] {len(zip_bytes)//1024}KB 取得")

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        geojson_files = [n for n in zf.namelist() if n.lower().endswith(".geojson")]
        if not geojson_files:
            raise FileNotFoundError(f"{pref_name}: GeoJSON なし")
        raw = zf.read(geojson_files[0])

    gdf = gpd.read_file(io.BytesIO(raw))
    # N03_007=行政区域コード, N03_001=都道府県, N03_004=市区町村
    gdf = gdf.rename(columns={"N03_007": "code", "N03_001": "pref", "N03_004": "city"})
    gdf = gdf[gdf["code"].notna()].copy()
    gdf["code"] = gdf["code"].astype(str).str.zfill(5)
    log.info(f"  [{pref_name}] {len(gdf)} ポリゴン")
    return gdf[["code", "pref", "city", "geometry"]]


def main():
    log.info("=== [補正] 市区町村境界の正しい再構築 ===")

    log.info("[1] 既存人口データ読み込み")
    pop = load_existing_population()

    log.info("[2] N03 ダウンロード & 結合")
    gdfs = []
    for pref_name, pref_code in PREF_CODES.items():
        gdfs.append(fetch_pref_gdf(pref_name, pref_code))
        time.sleep(1)
    allg = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs=gdfs[0].crs)
    log.info(f"  合計 {len(allg)} ポリゴン")

    log.info("[3] 5桁コードで dissolve（全ポリゴン結合）")
    # city/pref は最初の値を採用
    dissolved = allg.dissolve(by="code", aggfunc="first").reset_index()
    log.info(f"  dissolve後: {len(dissolved)} 市区町村")

    log.info("[4] 面積計算 (EPSG:6677)")
    dm = dissolved.to_crs(METRIC_CRS)
    dissolved["area_km2"] = (dm.geometry.area / 1_000_000).round(3)

    log.info("[5] 人口データをマージ")
    matched = 0
    for col in ["total_pop", "women_40plus", "women_total"]:
        dissolved[col] = 0
    for idx, row in dissolved.iterrows():
        p = pop.get(row["code"])
        if p:
            dissolved.at[idx, "total_pop"]    = p["total_pop"]
            dissolved.at[idx, "women_40plus"] = p["women_40plus"]
            dissolved.at[idx, "women_total"]  = p["women_total"]
            matched += 1
    log.info(f"  マージ: {matched}/{len(dissolved)}")

    log.info("[6] ジオメトリ簡略化")
    if dissolved.crs is None or dissolved.crs.to_epsg() != 4326:
        dissolved = dissolved.to_crs(epsg=4326)
    dissolved["geometry"] = dissolved["geometry"].simplify(SIMPLIFY_TOL, preserve_topology=True)
    dissolved = dissolved[~dissolved.geometry.is_empty & dissolved.geometry.notna()]

    log.info("[7] 保存")
    # area_csv
    dissolved[["code", "city", "pref", "area_km2"]].to_csv(AREA_CSV, index=False)
    log.info(f"  {AREA_CSV.name}")

    # geojson（座標精度4桁で出力）
    dissolved.to_file(WARD_GEOJSON, driver="GeoJSON")
    kb = WARD_GEOJSON.stat().st_size // 1024
    log.info(f"  {WARD_GEOJSON.name} ({kb}KB, {len(dissolved)} features)")

    # 検証
    log.info("=== 検証（主要市区町村の面積）===")
    check = {"13103": "港区", "13111": "大田区", "14205": "藤沢市", "12204": "船橋市"}
    for code, name in check.items():
        row = dissolved[dissolved["code"] == code]
        if len(row):
            log.info(f"  {name}({code}): {row.iloc[0]['area_km2']:.2f}km² "
                     f"人口{row.iloc[0]['total_pop']:,}")

    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
