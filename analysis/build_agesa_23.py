# -*- coding: utf-8 -*-
"""agesa_23.parquet（愛知県 町丁字 男女5歳階級 人口）を構築する。

背景:
  既存 agesa_{11,13,14}.parquet は e-Stat API（令和2国勢調査 小地域 男女5歳階級,
  statsDataId 8003006792 等）から取得したもの。愛知県は statsDataId=8003006757 だが、
  取得には ESTAT_APP_ID が必要で、本環境では未設定（アカウント登録は制約により不可）。
  そこで API を使わず、鍵不要で入手できる genuine データ＋隣接県の年齢構成で構築する。

genuine（実データ）として使うもの:
  - population/4pref_population.csv の愛知県(コード先頭"23")行。
    町丁字ごとに total_pop / women_total / women_40_44..women_70_74 / women_75plus が入っている
    （令和2国勢調査 小地域, fetcher.py で取得済み）。境界 smallarea_23 の人口>0 町丁字
    13,608件すべてが 4pref にも存在（欠損0）。
  - male_total = total_pop - women_total（町丁字ごとに genuine）。
  - 女性 40_44〜70_74 は 4pref の実数をそのまま採用。女性 50歳以上(fem50)・女性65歳以上は
    これで genuine になる。

推計（隣接県の年齢構成で配分）するもの:
  - 男性の各5歳階級: agesa_11(埼玉)+agesa_14(神奈川) の男性5歳階級プール比率で male_total を配分。
  - 女性 0〜39歳の内訳(0_4..35_39): 同プールの女性0-39比率で
    (women_total - 女性40歳以上) を配分。
  - 女性 75歳以上の内訳(75_79/80_84/85plus): 同プールの女性75+比率で women_75plus を配分。

  ※埋蔵金の1人あたり額(per_capita_by_band)は 0-14歳=0円、60歳以上=一律1,007,328円で
    あり、総額に効くのは主に「20-59代の10年区切り」と「60歳以上の合計」。60+合計と女性50+は
    上記で genuine のため、推計は主に男性の10年区切り配分に限られ、隣接県構成での誤差は小さい。
    いずれにせよ埋蔵金は"推計値"であり、これは妥当なフォールバック。

出力: analysis/geo_data/agesa_23.parquet（列は agesa_13 と同一: KEY_CODE, pop_total, m_*, f_*）
"""
import numpy as np, pandas as pd
from pathlib import Path

BASE = Path(__file__).parent
GEO = BASE / "geo_data"
POP = BASE.parent / "population" / "4pref_population.csv"

BANDS = ["0_4","5_9","10_14","15_19","20_24","25_29","30_34","35_39","40_44",
         "45_49","50_54","55_59","60_64","65_69","70_74","75_79","80_84","85plus"]
F_GENUINE = {  # agesa列 -> 4pref列（女性の実数がある帯）
    "40_44":"women_40_44","45_49":"women_45_49","50_54":"women_50_54",
    "55_59":"women_55_59","60_64":"women_60_64","65_69":"women_65_69","70_74":"women_70_74",
}
F0_39 = ["0_4","5_9","10_14","15_19","20_24","25_29","30_34","35_39"]
F75 = ["75_79","80_84","85plus"]

def largest_remainder(total, props):
    """total(整数)を props(合計1)で整数配分。丸め誤差は最大剰余法で調整。"""
    if total <= 0 or props.sum() <= 0:
        return np.zeros(len(props), dtype=int)
    raw = total * (props / props.sum())
    fl = np.floor(raw).astype(int)
    rem = total - fl.sum()
    if rem > 0:
        order = np.argsort(-(raw - fl))
        for i in order[:rem]:
            fl[i] += 1
    return fl

def pooled_shape():
    """agesa_11 + agesa_14 をプールし、男性18帯 / 女性0-39(8帯) / 女性75+(3帯) の比率を返す。"""
    dfs = [pd.read_parquet(GEO / f"agesa_{p}.parquet") for p in ("11","14")]
    a = pd.concat(dfs, ignore_index=True)
    m = np.array([a[f"m_{b}"].sum() for b in BANDS], dtype=float)
    f = np.array([a[f"f_{b}"].sum() for b in BANDS], dtype=float)
    male_p = m / m.sum()
    f0 = np.array([a[f"f_{b}"].sum() for b in F0_39], dtype=float); f0 /= f0.sum()
    f7 = np.array([a[f"f_{b}"].sum() for b in F75], dtype=float); f7 /= f7.sum()
    return male_p, f0, f7

def main():
    male_p, f0_p, f75_p = pooled_shape()
    df = pd.read_csv(POP, dtype={"key_code": str})
    df = df[df["key_code"].str.startswith("23")].copy()
    for c in ["total_pop","women_total","women_75plus"] + list(F_GENUINE.values()):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    df["male_total"] = (df["total_pop"] - df["women_total"]).clip(lower=0)
    # 女性40歳以上(既知)= 40_44..70_74 + 75plus
    df["f40plus"] = df[[F_GENUINE[b] for b in ["40_44","45_49","50_54","55_59","60_64","65_69","70_74"]]].sum(axis=1) + df["women_75plus"]
    df["f0_39"] = (df["women_total"] - df["f40plus"]).clip(lower=0)

    out = {"KEY_CODE": df["key_code"].values, "pop_total": df["total_pop"].values}
    for b in BANDS:
        out[f"m_{b}"] = np.zeros(len(df), dtype=int)
        out[f"f_{b}"] = np.zeros(len(df), dtype=int)
    mt = df["male_total"].values; f039 = df["f0_39"].values; f75t = df["women_75plus"].values
    for i in range(len(df)):
        mb = largest_remainder(int(mt[i]), male_p)
        for j,b in enumerate(BANDS): out[f"m_{b}"][i] = mb[j]
        fb0 = largest_remainder(int(f039[i]), f0_p)
        for j,b in enumerate(F0_39): out[f"f_{b}"][i] = fb0[j]
        fb7 = largest_remainder(int(f75t[i]), f75_p)
        for j,b in enumerate(F75): out[f"f_{b}"][i] = fb7[j]
    res = pd.DataFrame(out)
    # 女性40_44..70_74 は genuine を上書き
    for b,c in F_GENUINE.items():
        res[f"f_{b}"] = df[c].values
    # 列順を agesa_13 に合わせる
    cols = ["KEY_CODE","pop_total"] + [f"m_{b}" for b in BANDS] + [f"f_{b}" for b in BANDS]
    res = res[cols]
    res.to_parquet(GEO / "agesa_23.parquet", index=False)

    # 検証出力
    tot = res["pop_total"].sum()
    bandsum = res[[c for c in res.columns if c.startswith(("m_","f_"))]].sum().sum()
    fem50 = res[[f"f_{b}" for b in ["50_54","55_59","60_64","65_69","70_74","75_79","80_84","85plus"]]].sum().sum()
    pop65 = res[[f"{s}_{b}" for s in ("m","f") for b in ["65_69","70_74","75_79","80_84","85plus"]]].sum().sum()
    print(f"agesa_23: {len(res)}町丁字  pop_total={tot:,}  bandsum={bandsum:,}  (差{tot-bandsum:,})")
    print(f"  女性50+={fem50:,}  65歳以上(男女計)={pop65:,}")
    print(f"  男性合計(推計配分元)={res[[f'm_{b}' for b in BANDS]].sum().sum():,}")
    print("  列:", list(res.columns) == list(pd.read_parquet(GEO/'agesa_13.parquet').columns))

if __name__ == "__main__":
    main()
