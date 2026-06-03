"""
競合スクレイパー 共通基底クラス
出力スキーマ: name, brand, address, latitude, longitude,
             prefecture, city, phone, detail_url
"""
from __future__ import annotations
import json
import logging
import time
from pathlib import Path
from typing import Iterator

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TARGET_PREFS = ["東京都", "神奈川県", "埼玉県", "千葉県", "茨城県",
                "栃木県", "群馬県", "静岡県"]

DOCS_DATA = Path(__file__).parents[2] / "docs" / "data"
DOCS_DATA.mkdir(parents=True, exist_ok=True)


class CompetitorScraper:
    """競合店スクレイパーの基底クラス"""

    brand: str = ""          # "おたからや" 等
    sleep_sec: float = 1.0   # リクエスト間隔

    def __init__(self, log: logging.Logger | None = None):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.log = log or logging.getLogger(self.__class__.__name__)

    # ----------------------------------------------------------------
    # 必須オーバーライド
    # ----------------------------------------------------------------

    def fetch_stores(self, prefs: list[str] = None) -> list[dict]:
        """1都3県の店舗データを返す（サブクラスで実装）"""
        raise NotImplementedError

    # ----------------------------------------------------------------
    # ユーティリティ
    # ----------------------------------------------------------------

    def get(self, url: str, **kwargs) -> requests.Response:
        """スリープ付き GET"""
        time.sleep(self.sleep_sec)
        r = self.session.get(url, timeout=30, **kwargs)
        r.raise_for_status()
        return r

    @staticmethod
    def make_record(
        name: str,
        brand: str,
        address: str,
        prefecture: str,
        city: str = "",
        phone: str = "",
        detail_url: str = "",
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> dict:
        """統一スキーマのレコードを生成"""
        return {
            "name":        name.strip(),
            "brand":       brand,
            "address":     address.strip(),
            "latitude":    latitude,
            "longitude":   longitude,
            "prefecture":  prefecture,
            "city":        city.strip(),
            "phone":       phone.strip(),
            "detail_url":  detail_url,
        }

    def save(self, stores: list[dict], filename: str) -> Path:
        """docs/data/ に JSON 保存"""
        out = DOCS_DATA / filename
        with open(out, "w", encoding="utf-8") as f:
            json.dump(stores, f, ensure_ascii=False, indent=2)
        self.log.info(f"  保存: {out.name} ({len(stores)} 件)")
        return out
