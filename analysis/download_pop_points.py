"""
人口点群の構築（メッシュ商圏人口の算出用）

各候補地点の「半径内に住む40歳以上女性」を市単位ではなく細かい粒度で
評価するため、町丁字(小地域)centroid + 女性40+人口 の点群を作る。
田畑・山林には町丁字点が無い/人口0 → 無人地帯の商圏人口が自動的に薄くなる。

データソース:
  境界(centroid座標): e-Stat 統計GIS 小地域境界 令和2年国勢調査
    https://www.e-stat.go.jp/gis/statmap-search/data?dlserveyId=A002005212020&code={pref}&format=shape&downloadType=5
    （X_CODE=経度, Y_CODE=緯度, 9桁コード=PREF+CITY+KIHON1）
  人口: population/4pref_population.csv（小地域 女性40歳以上人口, 9桁）
  取得日: 2026-06-03

出力: analysis/pop_points.csv (lat, lng, women_40plus)  ※女性40+>0のみ
"""
import csv
import logging
import zipfile
from pathlib import Path

import requests
import geopandas as gpd

BASE_DIR = Path(__file__).parent
GEO = BASE_DIR / "geo_data"
GEO.mkdir(exist_ok=True)
LOG_PATH = BASE_DIR / "progress.log"
OUT_CSV = BASE_DIR / "pop_points.csv"
POP_CSV = BASE_DIR.parent / "population" / "4pref_population.csv"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

PREF_CODES = ["08", "09", "10", "11", "12", "13", "14", "19", "20", "22", "23"]
URL = ("https://www.e-stat.go.jp/gis/statmap-search/data"
       "?dlserveyId=A002005212020&code={code}&coordSys=1&format=shape&downloadType=5&datum=2000")


def load_pop_lookup():
    """9桁 key_code -> 女性40+人口（9桁=町丁字 総数のみ採用）"""
    lk = {}
    for r in csv.DictReader(open(POP_CSV, encoding="utf-8-sig")):
        kc = r["key_code"]
        if len(kc) == 9:  # 9桁(町丁字)のみ。11桁(丁目)は内訳なので除外し二重計上回避
            try:
                lk[kc] = int(r["women_40plus"])
            except (ValueError, KeyError):
                pass
    return lk


def fetch_pref(code):
    zp = GEO / f"smallarea_{code}.zip"
    if not zp.exists() or zp.stat().st_size < 10000:
        log.info(f"  [{code}] DL")
        r = requests.get(URL.format(code=code), headers={"User-Agent": "Mozilla/5.0"}, timeout=300)
        r.raise_for_status()
        zp.write_bytes(r.content)
    with zipfile.ZipFile(zp) as z:
        shp = [n for n in z.namelist() if n.lower().endswith(".shp")][0]
    return gpd.read_file(f"zip://{zp}!{shp}", encoding="cp932")


def main():
    log.info("=== 人口点群 構築 ===")
    pop = load_pop_lookup()
    log.info(f"  人口辞書(9桁町丁字): {len(pop)}")

    points = []   # (lat, lng, women)
    pref_sum = {}
    for code in PREF_CODES:
        gdf = fetch_pref(code)
        # 1町丁字(code9)に複数ポリゴン(基本単位区/飛び地)があるため、
        # code9 ごとに最大面積の代表ポリゴンを1つ選び、人口を一度だけ計上する
        rep = {}  # code9 -> (area, y, x)
        for _, row in gdf.iterrows():
            city = str(row.get("CITY", "") or "").zfill(3)
            kihon1 = str(row.get("KIHON1", "") or "").zfill(4)
            code9 = f"{code}{city}{kihon1}"
            if code9 not in pop or pop[code9] <= 0:
                continue
            x = row.get("X_CODE"); y = row.get("Y_CODE")
            if x is None or y is None or x != x or y != y:
                continue
            area = row.get("AREA", 0) or 0
            if code9 not in rep or area > rep[code9][0]:
                rep[code9] = (area, float(y), float(x))
        n = 0
        for code9, (_, y, x) in rep.items():
            w = pop[code9]
            points.append((round(y, 6), round(x, 6), w))
            n += 1
            pref_sum[code] = pref_sum.get(code, 0) + w
        log.info(f"  [{code}] 点数{n} 女性40+合計{pref_sum.get(code,0):,}")

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["lat", "lng", "women_40plus"])
        wr.writerows(points)
    log.info(f"  保存: {OUT_CSV.name} ({len(points)}点, {OUT_CSV.stat().st_size//1024}KB)")
    log.info(f"  全県 女性40+合計: {sum(pref_sum.values()):,}")
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
