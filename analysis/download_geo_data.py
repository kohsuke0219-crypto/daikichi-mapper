"""
ステップ10-1: 地理的分断要素データ ダウンローダー

取得データ:
  P13  … 都市公園（面積1ha+の公園を分断要因に使用）
  W05  … 河川（幅員10m+を分断要因に使用）
  G04a … 標高・傾斜度3次メッシュ（標高150m+を山地として使用）
  L03b … 土地利用細分メッシュ（住宅地比率算出に使用）

  ※ MLIT コード A33 は「地すべり防止区域」であり都市公園ではないため P13 を使用

出力: analysis/geo_data/{type}_{key}.zip
ログ: analysis/progress.log
"""
import sys
import time
from pathlib import Path
from datetime import datetime
import logging
import requests

# ---------------------------------------------------------------------------
# パス・ロギング設定
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
GEO_DATA_DIR = BASE_DIR / "geo_data"
GEO_DATA_DIR.mkdir(exist_ok=True)

LOG_PATH = BASE_DIR / "progress.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 対象地域
# ---------------------------------------------------------------------------
PREF_CODES = {
    "東京都":   "13",
    "神奈川県": "14",
    "埼玉県":   "11",
    "千葉県":   "12",
}

# 関東4都県をカバーする1次メッシュコード
# 1次メッシュ = floor(lat*1.5)×100 + floor(lon-100)
# 5239:lat34.67-35.33/lon139-140  5338:lat35.33-36.0/lon138-139  etc.
KANTO_MESH_CODES = [
    "5238", "5239", "5240",
    "5338", "5339", "5340",
    "5438", "5439", "5440",
]

# ---------------------------------------------------------------------------
# URL候補（上から順に試行、最初に成功したものを使う）
# ---------------------------------------------------------------------------
URL_PATTERNS = {
    "P13": [
        "https://nlftp.mlit.go.jp/ksj/gml/data/P13/P13-11/P13-11_{key}_GML.zip",
    ],
    "W05": [
        "https://nlftp.mlit.go.jp/ksj/gml/data/W05/W05-09/W05-09_{key}_GML.zip",
        "https://nlftp.mlit.go.jp/ksj/gml/data/W05/W05-08/W05-08_{key}_GML.zip",
        "https://www.ksj.mlit.go.jp/ksj/download/W05-09_{key}_GML.zip",
        "https://www.ksj.mlit.go.jp/ksj/download/W05-08_{key}_GML.zip",
    ],
    "G04a": [
        "https://nlftp.mlit.go.jp/ksj/gml/data/G04-a/G04-a-11/G04-a-11_{key}-jgd_GML.zip",
        "https://nlftp.mlit.go.jp/ksj/gml/data/G04-a/G04-a-11_{key}-jgd_GML.zip",
    ],
    "L03b": [
        "https://nlftp.mlit.go.jp/ksj/gml/data/L03-b/L03-b-16/L03-b-16_{key}-jgd_GML.zip",
        "https://nlftp.mlit.go.jp/ksj/gml/data/L03-b-16_{key}-jgd_GML.zip",
        "https://nlftp.mlit.go.jp/ksj/gml/data/L03-b/L03-b-16_{key}-jgd_GML.zip",
    ],
}

# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def probe_url(url: str, timeout: int = 15) -> bool:
    """URL が存在するか HEAD リクエストで確認する"""
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        return r.status_code == 200
    except Exception:
        return False


def download_zip(url: str, out_path: Path, timeout: int = 300) -> bool:
    """ZIP をストリームダウンロードして保存。成功で True。"""
    try:
        r = requests.get(url, timeout=timeout, stream=True)
        r.raise_for_status()
        size = 0
        with open(out_path, "wb") as fh:
            for chunk in r.iter_content(chunk_size=65536):
                fh.write(chunk)
                size += len(chunk)
        log.info(f"    完了: {out_path.name}  ({size // 1024} KB)")
        return True
    except Exception as e:
        log.warning(f"    ダウンロード失敗 ({url}): {e}")
        if out_path.exists():
            out_path.unlink()
        return False


def resolve_and_download(data_type: str, key: str) -> bool:
    """URL パターンを順番に試してダウンロードする。既存ファイルはスキップ。"""
    out_path = GEO_DATA_DIR / f"{data_type}_{key}.zip"
    if out_path.exists() and out_path.stat().st_size > 1024:
        log.info(f"  スキップ（既存 {out_path.stat().st_size // 1024} KB）: {out_path.name}")
        return True

    for pattern in URL_PATTERNS[data_type]:
        url = pattern.format(key=key)
        log.info(f"  試行: {url}")
        if probe_url(url):
            return download_zip(url, out_path)

    log.error(f"  全URLで失敗: {data_type} / key={key}")
    return False

# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main():
    test_mode = "--test" in sys.argv
    log.info(f"=== ステップ10-1 ダウンロード開始 {'[テストモード]' if test_mode else ''} ===")

    if test_mode:
        # 東京 P13 のみでURL疎通確認
        log.info("[TEST] 東京 P13 (都市公園)")
        ok = resolve_and_download("P13", "13")
        log.info(f"[TEST] 結果: {'成功' if ok else '失敗'}")
        return

    # ---- 1. 都道府県別データ（P13 / W05）----
    log.info("[1/2] 都道府県別データ（P13: 都市公園 / W05: 河川）")
    for pref_name, code in PREF_CODES.items():
        log.info(f"  [{pref_name}]")
        resolve_and_download("P13", code)
        resolve_and_download("W05", code)
        time.sleep(1)

    # ---- 2. メッシュ別データ（G04a / L03b）----
    log.info("[2/2] メッシュ別データ（G04a: 標高 / L03b: 土地利用）")
    for mesh in KANTO_MESH_CODES:
        log.info(f"  [メッシュ {mesh}]")
        resolve_and_download("G04a", mesh)
        resolve_and_download("L03b", mesh)
        time.sleep(0.5)

    log.info("=== ダウンロード完了 ===")


if __name__ == "__main__":
    main()
