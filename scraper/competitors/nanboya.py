"""
ステップ11-2: なんぼやスクレイパー

対象URL: https://nanboya.com/shop/{pref_slug}/
構造: section.store-detail > h3.shopname-heading + div.tab-content
住所: div.tab-content のテキストから 〒XXXXX の次行を抽出
"""
from __future__ import annotations
import re
import logging
from pathlib import Path

from bs4 import BeautifulSoup

from .base import CompetitorScraper, TARGET_PREFS

log = logging.getLogger(__name__)

PREF_SLUGS = {
    "東京都":   "tokyo",
    "神奈川県": "kanagawa",
    "埼玉県":   "saitama",
    "千葉県":   "chiba",
    "茨城県":   "ibaraki",
}

BASE_URL = "https://nanboya.com/shop"
BRAND    = "なんぼや"


def extract_address(tab_text: str) -> str:
    """div.tab-content のテキストから住所を抽出する。
    パターン: 〒XXX-XXXX の次の行に住所がある。
    """
    lines = [l.strip() for l in tab_text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        if re.match(r'^〒\d{3}-\d{4}$', line):
            if i + 1 < len(lines):
                return f"{line} {lines[i + 1]}"
            return line
    # フォールバック: 都道府県名を含む行
    for line in lines:
        if re.search(r'[都道府県]', line) and re.search(r'[0-9０-９]', line):
            return line
    return ""


class NanboyaScraper(CompetitorScraper):
    brand = BRAND

    def fetch_stores(self, prefs: list[str] = None) -> list[dict]:
        target = prefs or TARGET_PREFS
        all_stores: list[dict] = []

        for pref in target:
            slug = PREF_SLUGS.get(pref)
            if not slug:
                continue
            url = f"{BASE_URL}/{slug}/"
            log.info(f"  [{pref}] {url}")

            r = self.get(url)
            soup = BeautifulSoup(r.text, "html.parser")

            sections = soup.find_all("section", class_="store-detail")
            log.info(f"    {len(sections)} 店舗")

            for sec in sections:
                # 店舗名
                h3 = sec.find("h3", class_="shopname-heading")
                if not h3:
                    continue
                name_raw = h3.get_text(strip=True)
                # ｢なんぼや｣〜 → 〜 だけ残す（括弧含む場合あり）
                name = re.sub(r'^[｢「]なんぼや[｣」]\s*', "", name_raw).strip()
                if not name:
                    name = name_raw

                # 住所
                tab = sec.find("div", class_="tab-content")
                tab_text = tab.get_text(separator="\n", strip=True) if tab else ""
                address = extract_address(tab_text)

                # 詳細URL
                detail_link = sec.find("a", href=lambda h: h and "/shop/" in h and
                                       "/customer-review/" not in h and
                                       h != f"/shop/{slug}/")
                detail_url = detail_link["href"] if detail_link else ""

                store = self.make_record(
                    name=name,
                    brand=BRAND,
                    address=address,
                    prefecture=pref,
                    detail_url=detail_url,
                )
                all_stores.append(store)

        log.info(f"  なんぼや 合計: {len(all_stores)} 件")
        return all_stores


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    scraper = NanboyaScraper(log=log)
    stores = scraper.fetch_stores()
    print(f"\n取得完了: {len(stores)} 件")
    for s in stores[:5]:
        print(f"  {s['name']} / {s['address'][:50]}")
    scraper.save(stores, "competitors_nanboya.json")
