"""
人流（滞在人口）レイヤー用データ生成。

データ元: 国土交通省「全国の人流オープンデータ」1kmメッシュ滞在人口
  (monthly_mdp_mesh1km) https://www.geospatial.jp/ckan/dataset/mlit-1km-fromto
  スキーマ: mesh1kmid,prefcode,citycode,year,month,dayflag,timezone,population
    dayflag  0=休日 / 1=平日 / 2=全日
    timezone 0=昼間(11-14時台) / 2=深夜(2-4時台=居住相当)
  対象年: 2021年（12か月平均）。対象: 1都10県。

集計:
  wd_day = 平日昼   (dayflag=1, timezone=0) の12か月平均
  hd_day = 休日昼   (dayflag=0, timezone=0) の12か月平均
  night  = 深夜(居住)(dayflag=2, timezone=2) の12か月平均

出力:
  docs/data/people_flow_1km.json    {"<mesh8桁>": {"wd_day":n,"hd_day":n,"night":n}, ...}
  docs/data/people_flow_1km.geojson 1kmメッシュのポリゴン(EPSG:4326) props mesh/wd_day/hd_day/night
"""
import io
import json
import logging
import urllib.request
import zipfile
from pathlib import Path

BASE = Path(__file__).parent
GEO = BASE / "geo_data"
GEO.mkdir(exist_ok=True)
OUT_JSON = BASE.parent / "docs" / "data" / "people_flow_1km.json"
OUT_GEO = BASE.parent / "docs" / "data" / "people_flow_1km.geojson"
LOG = BASE / "progress.log"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler()])
log = logging.getLogger(__name__)

DS = "8fd79f08-00e6-4d14-9c89-e3bdca66af11"
BASEURL = f"https://www.geospatial.jp/ckan/dataset/{DS}/resource/{{rid}}/download/monthly_mdp_mesh1km_{{code}}.zip"
PREF_RID = {
    "08": "ff8817c6-b73e-4b0e-8512-960c672608b8", "09": "165f2778-753e-4fc0-b5ad-158255bfcb59",
    "10": "f9ddafcd-edc5-4a75-8895-0765f3f64fd3", "11": "81f53fdd-5588-45d0-b917-c599903c8da9",
    "12": "2f3a10cf-6e61-4c2a-b74d-a2ba8fb5cbed", "13": "3b69ffab-2fb8-4901-9cf3-9da2c19e3351",
    "14": "2faa20e9-2007-4a6a-bf6a-f5ece6823707", "19": "2e4922f2-8658-499b-91ea-a1eb4b481473",
    "20": "71ec4371-54fb-47c4-80c3-f51c3d846059", "22": "6c3fa1f5-a398-4699-9154-0559ad354e08",
    "23": "1ee9aa41-2980-4801-a218-08acba4737d4",
}
YEAR = "2021"


def download(code, rid):
    p = GEO / f"pf_{code}.zip"
    if p.exists() and p.stat().st_size > 100000:
        return p
    url = BASEURL.format(rid=rid, code=code)
    log.info(f"  DL {code}: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        p.write_bytes(r.read())
    return p


def mesh_to_poly(code):
    """3次メッシュ(1km)8桁コード → (lng配列, lat配列) の四隅ポリゴン(反時計回り閉じ)"""
    p = int(code[0:2]); q = int(code[2:4])
    r = int(code[4]); s = int(code[5])
    t = int(code[6]); u = int(code[7])
    lat0 = p / 1.5 + r * (1/12) + t * (1/120)
    lng0 = q + 100 + s * (1/8) + u * (1/80)
    dlat, dlng = 1/120, 1/80
    la1, la2 = round(lat0, 6), round(lat0 + dlat, 6)
    lo1, lo2 = round(lng0, 6), round(lng0 + dlng, 6)
    return [[lo1, la1], [lo2, la1], [lo2, la2], [lo1, la2], [lo1, la1]]


def main():
    log.info("=== 人流(滞在人口) 整形 ===")
    # mesh -> [wd_sum,wd_n, hd_sum,hd_n, ni_sum,ni_n]
    agg = {}
    for code, rid in PREF_RID.items():
        zpath = download(code, rid)
        z = zipfile.ZipFile(zpath)
        months = 0
        for mm in [f"{m:02d}" for m in range(1, 13)]:
            inner_name = f"{code}/{YEAR}/{mm}/monthly_mdp_mesh1km.csv.zip"
            if inner_name not in z.namelist():
                continue
            months += 1
            z2 = zipfile.ZipFile(io.BytesIO(z.read(inner_name)))
            csvname = [n for n in z2.namelist() if n.endswith(".csv")][0]
            for line in z2.read(csvname).decode("utf-8", "replace").splitlines()[1:]:
                f = line.split(",")
                if len(f) < 8:
                    continue
                mesh, day, tz, pop = f[0], f[5], f[6], f[7]
                try:
                    v = int(pop)
                except ValueError:
                    continue
                a = agg.get(mesh)
                if a is None:
                    a = [0, 0, 0, 0, 0, 0]; agg[mesh] = a
                if tz == "0" and day == "1":   a[0] += v; a[1] += 1  # 平日昼
                elif tz == "0" and day == "0": a[2] += v; a[3] += 1  # 休日昼
                elif tz == "2" and day == "2": a[4] += v; a[5] += 1  # 深夜(居住)
        log.info(f"  [{code}] {months}か月 / 累計メッシュ{len(agg)}")

    # 平均化
    flow = {}
    for mesh, a in agg.items():
        wd = round(a[0] / a[1]) if a[1] else 0
        hd = round(a[2] / a[3]) if a[3] else 0
        ni = round(a[4] / a[5]) if a[5] else 0
        if wd == 0 and hd == 0 and ni == 0:
            continue
        flow[mesh] = {"wd_day": wd, "hd_day": hd, "night": ni}

    OUT_JSON.write_text(json.dumps(flow, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info(f"  保存: {OUT_JSON.name} ({len(flow)}メッシュ, {OUT_JSON.stat().st_size//1024}KB)")

    # geojson ポリゴン
    feats = []
    for mesh, v in flow.items():
        if len(mesh) != 8:
            continue
        feats.append({
            "type": "Feature",
            "properties": {"mesh": mesh, "wd_day": v["wd_day"], "hd_day": v["hd_day"], "night": v["night"]},
            "geometry": {"type": "Polygon", "coordinates": [mesh_to_poly(mesh)]},
        })
    gj = {"type": "FeatureCollection", "features": feats}
    OUT_GEO.write_text(json.dumps(gj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info(f"  保存: {OUT_GEO.name} ({len(feats)}メッシュ, {OUT_GEO.stat().st_size//1024}KB)")
    # 参考分布
    import statistics as st
    wdv = sorted(v["wd_day"] for v in flow.values())
    log.info(f"  wd_day 中央値{wdv[len(wdv)//2]} / 最大{wdv[-1]}")
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
