"""
新規オープン予定店レイヤー: スーパー・複合施設の出店告知をキュレーション

データソース(取得日 2026-05-29 / 公開ニュース・各社告知より手動収集):
  - 流通ニュース ヤオコー25年度新規7店 https://www.ryutsuu.biz/store/r051312.html
  - 流通ニュース 日本SC協会26年新規23施設 https://www.ryutsuu.biz/store/r121612.html
  - スーパーマーケットファン オーケー出店予定 https://supermarket-fan.jp/supermarket/post_1537
  - 三井不動産/イオンモール各社ニュースリリース・大店立地法届出公告
  - 府中ららぽーと(旧調布基地跡地)各種報道

方針: 網羅性より正確性を優先。座標が特定できないものは別途リスト化して報告。
      オープン時期はソース記載のまま。判明しないものは「時期未定」。

出力: docs/data/new_openings.json
  [{name, category, chain, prefecture, opening, address, lat, lng}]
"""
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests

BASE_DIR  = Path(__file__).parent
DOCS_DATA = BASE_DIR.parent / "docs" / "data"
LOG_PATH  = BASE_DIR / "progress.log"
OUT_PATH  = DOCS_DATA / "new_openings.json"
UNLOCATED = BASE_DIR / "new_openings_unlocated.txt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# ---- キュレーション済み 出店告知リスト ----
# (店名, チェーン, カテゴリ, 都県, オープン時期, ジオコーディング用住所)
OPENINGS = [
    # ヤオコー(流通ニュース r051312)
    ("ヤオコー杉並桃井店",   "ヤオコー", "スーパー", "東京都", "2025年6月",     "東京都杉並区桃井3丁目"),
    ("ヤオコー松戸古ケ崎店", "ヤオコー", "スーパー", "千葉県", "2025年6月",     "千葉県松戸市古ケ崎"),
    ("ヤオコーまるひろ上尾店","ヤオコー","スーパー", "埼玉県", "2025年度上期",   "埼玉県上尾市宮本町"),
    ("ヤオコー板橋四葉店",   "ヤオコー", "スーパー", "東京都", "2025年度下期",   "東京都板橋区四葉2丁目"),
    ("ヤオコー岩槻本丸店",   "ヤオコー", "スーパー", "埼玉県", "2025年度下期",   "埼玉県さいたま市岩槻区本丸"),
    ("ヤオコー福生牛浜店",   "ヤオコー", "スーパー", "東京都", "2025年度下期",   "東京都福生市牛浜"),
    ("ヤオコー東戸塚店",     "ヤオコー", "スーパー", "神奈川県","2026年3月",     "神奈川県横浜市戸塚区品濃町"),
    # オーケー(スーパーマーケットファン)
    ("オーケー小岩駅前店",   "オーケー", "スーパー", "東京都", "2026年3月",     "東京都江戸川区南小岩7丁目"),
    ("オーケー大泉インター店","オーケー","スーパー", "東京都", "2026年1月",     "東京都練馬区大泉学園町9丁目"),
    ("オーケー松戸大橋店",   "オーケー", "スーパー", "千葉県", "2025年11月",    "千葉県松戸市大橋242-1"),
    ("オーケー和光新倉店",   "オーケー", "スーパー", "埼玉県", "2025年10月",    "埼玉県和光市新倉5丁目"),
    ("オーケー越谷大井店",   "オーケー", "スーパー", "埼玉県", "2025年3月",     "埼玉県越谷市大井塚田440-1"),
    ("オーケー新座石神店",   "オーケー", "スーパー", "埼玉県", "2025年4月",     "埼玉県新座市石神1-6-14"),
    ("オーケー綾瀬駅前店",   "オーケー", "スーパー", "東京都", "2025年11月",    "東京都葛飾区小菅4-10-3"),
    # ベルク
    ("ベルク川崎下作延店",   "ベルク",   "スーパー", "神奈川県","2026年4月",     "神奈川県川崎市高津区下作延"),
    ("ベルク入間下藤沢店",   "ベルク",   "スーパー", "埼玉県", "2028年春",      "埼玉県入間市下藤沢"),
    # 複合施設
    ("イオンモール津田沼South","イオンモール","複合施設","千葉県","2026年3月",   "千葉県習志野市津田沼1丁目"),
    ("ららぽーと府中",       "ららぽーと","複合施設","東京都", "2029年予定",    "東京都府中市浅間町1丁目"),
]


def load_api_key() -> str:
    env_file = Path(r"C:/Users/user/Documents/daikichi-secrets/set_env.ps1")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "GOOGLE_MAPS_API_KEY" in line and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("GOOGLE_MAPS_API_KEY", "")


def geocode(addr: str, key: str):
    try:
        r = requests.get("https://maps.googleapis.com/maps/api/geocode/json",
                         params={"address": addr, "key": key, "region": "jp",
                                 "language": "ja"}, timeout=20)
        d = r.json()
        if d.get("status") == "OK" and d["results"]:
            loc = d["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception as e:
        log.warning(f"  geocode失敗: {addr}: {e}")
    return None, None


def main():
    log.info("=== 新規オープン予定店 構築 ===")
    key = load_api_key()
    if not key:
        log.error("GOOGLE_MAPS_API_KEY が見つかりません")
        sys.exit(1)
    log.info(f"  APIキー: {key[:10]}...")

    located, unlocated = [], []
    for name, chain, cat, pref, opening, addr in OPENINGS:
        lat, lng = geocode(addr, key)
        time.sleep(0.15)
        if lat:
            located.append({
                "name": name, "category": cat, "chain": chain,
                "prefecture": pref, "opening": opening,
                "address": addr, "lat": round(lat, 6), "lng": round(lng, 6),
            })
            log.info(f"  ○ {name} → {lat:.4f},{lng:.4f} ({opening})")
        else:
            unlocated.append((name, chain, cat, pref, opening, addr))
            log.info(f"  × {name} → 座標未特定 ({addr})")

    OUT_PATH.write_text(json.dumps(located, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    log.info(f"  保存: {OUT_PATH.name} ({len(located)}件)")

    if unlocated:
        lines = ["# 新規オープン予定店 - 座標未特定リスト", ""]
        for name, chain, cat, pref, opening, addr in unlocated:
            lines.append(f"- {name}（{chain}・{cat}）{pref} / {opening} / {addr}")
        UNLOCATED.write_text("\n".join(lines), encoding="utf-8")
        log.info(f"  未特定リスト: {UNLOCATED.name} ({len(unlocated)}件)")

    # 集計
    log.info("=== 集計 ===")
    import collections
    by_cat = collections.Counter(o["category"] for o in located)
    by_pref = collections.Counter(o["prefecture"] for o in located)
    log.info(f"  業態別(座標特定済): {dict(by_cat)}")
    log.info(f"  都県別(座標特定済): {dict(by_pref)}")
    log.info(f"  座標特定 {len(located)} / 未特定 {len(unlocated)} / 計 {len(OPENINGS)}")
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
