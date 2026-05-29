"""
[フェーズ12 補正2] 人口データの二重計上を修正

問題: e-Stat小地域データは9桁(字)と11桁(丁目)の2階層を含み、
build_geojsonが両方を合算 → 人口が約2倍（東京27M vs 実14M）。
11桁は9桁の内訳なので、9桁のみ集計すれば正しい（孤立11桁は0件で検証済み）。

修正: 4pref_population.csv を9桁のみで5桁コードに再集計し、
ward_population.geojson の total_pop/women_40plus/women_total を上書き。

出力: docs/data/ward_population.geojson（人口値のみ更新）
       analysis/ward_pop_fixed.csv
"""
import csv
import json
import logging
from pathlib import Path

BASE_DIR  = Path(__file__).parent
DOCS_DATA = BASE_DIR.parent / "docs" / "data"
LOG_PATH  = BASE_DIR / "progress.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

POP_CSV      = BASE_DIR.parent / "population" / "4pref_population.csv"
WARD_GEOJSON = DOCS_DATA / "ward_population.geojson"
OUT_CSV      = BASE_DIR / "ward_pop_fixed.csv"


def aggregate_9digit() -> dict:
    """9桁コードのみで5桁コードに集計"""
    ward = {}
    with open(POP_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = row["key_code"]
            if len(key) != 9:   # 9桁(字)のみ。11桁(丁目)は内訳なので除外
                continue
            code = key[:5]
            if code not in ward:
                ward[code] = {"total_pop": 0, "women_total": 0, "women_40plus": 0}
            ward[code]["total_pop"]    += int(row["total_pop"])
            ward[code]["women_total"]  += int(row["women_total"])
            ward[code]["women_40plus"] += int(row["women_40plus"])
    log.info(f"  9桁集計: {len(ward)} 市区町村")
    return ward


def main():
    log.info("=== [補正2] 人口二重計上の修正 ===")

    log.info("[1] 9桁コードで再集計")
    ward = aggregate_9digit()

    log.info("[2] geojson の人口値を上書き")
    with open(WARD_GEOJSON, encoding="utf-8") as f:
        data = json.load(f)

    updated = 0
    rows = []
    for feat in data["features"]:
        p = feat["properties"]
        code = str(p.get("code", "")).zfill(5)
        fixed = ward.get(code)
        if fixed:
            p["total_pop"]    = fixed["total_pop"]
            p["women_40plus"] = fixed["women_40plus"]
            p["women_total"]  = fixed["women_total"]
            updated += 1
        rows.append({
            "code": code, "city": p.get("city", ""), "pref": p.get("pref", ""),
            "total_pop": p.get("total_pop", 0),
            "women_40plus": p.get("women_40plus", 0),
            "area_km2": p.get("area_km2", ""),
        })
    log.info(f"  更新: {updated}/{len(data['features'])}")

    with open(WARD_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    log.info(f"  保存: {WARD_GEOJSON.name} ({WARD_GEOJSON.stat().st_size//1024}KB)")

    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["code","city","pref","total_pop","women_40plus","area_km2"])
        w.writeheader(); w.writerows(rows)
    log.info(f"  {OUT_CSV.name}")

    # 検証
    log.info("=== 検証 ===")
    tot = {}
    for r in rows:
        pref = r["pref"]
        tot[pref] = tot.get(pref, 0) + r["total_pop"]
    for k, v in tot.items():
        log.info(f"  {k}: {v:,}")
    log.info(f"  合計: {sum(tot.values()):,} (実値 約3682万)")
    for code, name in [("13103","港区"),("13104","新宿区"),("13101","千代田区")]:
        r = next((x for x in rows if x["code"]==code), None)
        if r:
            log.info(f"  {name}: {r['total_pop']:,}")

    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
