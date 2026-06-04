"""
機能1（クリック地点 半径n km圏内人口集計）用:
人口メッシュ点群 pop_points.csv を、フロントエンドで読み込めるコンパクトJSONに変換する。

入力 : analysis/pop_points.csv  (lat, lng, women_40plus / 町丁字centroid × 女性40歳以上人口, 19,063点)
出力 : docs/data/pop_points.json
        { "indicator": "women_40plus", "label": "40歳以上女性人口",
          "source": "e-Stat 統計GIS 小地域境界(dlserveyId=A002005212020) × 令和2年国勢調査 女性40歳以上人口",
          "granularity": "町丁字（小地域）centroid",
          "points": [[lat, lng, women], ...] }

※ 集計指標は「40歳以上女性人口(women_40plus)」。マップのコロプレス指標と一致。
※ 円内集計は centroid を点として半径内に入るか判定する近似（厳密なメッシュ面積按分ではない）。
"""
import csv
import json
from pathlib import Path

BASE = Path(__file__).parent
SRC  = BASE / "pop_points.csv"
OUT  = BASE.parent / "docs" / "data" / "pop_points.json"

INDICATOR = "women_40plus"
LABEL     = "40歳以上女性人口"
SOURCE    = ("e-Stat 統計GIS 小地域境界(dlserveyId=A002005212020) の町丁字centroid × "
            "令和2年国勢調査 女性40歳以上人口")
GRANULARITY = "町丁字（小地域）centroid"


def main():
    points = []
    total = 0
    with open(SRC, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lat = round(float(row["lat"]), 5)
                lng = round(float(row["lng"]), 5)
                w   = int(float(row["women_40plus"]))
            except (ValueError, KeyError):
                continue
            if w <= 0:
                continue
            points.append([lat, lng, w])
            total += w

    out = {
        "indicator": INDICATOR,
        "label": LABEL,
        "source": SOURCE,
        "granularity": GRANULARITY,
        "n_points": len(points),
        "total": total,
        "points": points,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    print(f"saved {OUT} : {len(points)} points, total women_40plus={total:,}, "
          f"{OUT.stat().st_size//1024}KB")


if __name__ == "__main__":
    main()
