"""買取大吉の店舗ページから店舗情報を取得するスクレイパー。

地区別ページ（kanto, kinki-tiku など）には店舗情報が HTML として
そのまま埋め込まれているので、requests + BeautifulSoup で十分。
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Iterator
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

BASE_URL = "https://www.kaitori-daikichi.jp"

# 地区スラッグ → 地区名のマップ。サイト側の URL 構造に依存。
REGIONS: dict[str, str] = {
    "hokkaido-tohoku": "北海道・東北",
    "kanto": "関東",
    "tyubu": "中部",
    "kinki-tiku": "近畿",
    "tyugoku-sikoku": "中国・四国",
    "kyusyu-okinawa": "九州・沖縄",
}

# 都道府県名を住所頭から抽出するための正規表現（北海道〜沖縄まで）
PREFECTURE_RE = re.compile(
    r"^(北海道|青森県|岩手県|宮城県|秋田県|山形県|福島県|"
    r"茨城県|栃木県|群馬県|埼玉県|千葉県|東京都|神奈川県|"
    r"新潟県|富山県|石川県|福井県|山梨県|長野県|岐阜県|静岡県|愛知県|"
    r"三重県|滋賀県|京都府|大阪府|兵庫県|奈良県|和歌山県|"
    r"鳥取県|島根県|岡山県|広島県|山口県|"
    r"徳島県|香川県|愛媛県|高知県|"
    r"福岡県|佐賀県|長崎県|熊本県|大分県|宮崎県|鹿児島県|沖縄県)"
)


@dataclass
class Store:
    """単一店舗の情報。"""

    store_id: str  # サイト側スラッグ（例: utsunomiya-mine）
    name: str
    region: str
    prefecture: str
    address: str
    closed_days: str
    business_hours: str
    phone: str
    detail_url: str
    map_url: str
    # 緯度経度は後段の geocoder で埋める
    latitude: float | None = None
    longitude: float | None = None
    # サイト側に変更があったか判定するためのハッシュ
    content_hash: str = ""

    def compute_hash(self) -> str:
        """ジオコーディング結果を含めない、サイト上の表示内容のハッシュ。

        住所が変わったら再ジオコーディングする判定に使う。
        """
        key = "|".join(
            [self.name, self.address, self.business_hours, self.closed_days, self.phone]
        )
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def fetch_region_html(region_slug: str, session: requests.Session | None = None) -> str:
    """指定地区の HTML を取得する。"""
    url = f"{BASE_URL}/store/{region_slug}/"
    sess = session or requests.Session()
    sess.headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (compatible; DaikichiStoreScraper/1.0; +https://github.com/your/repo)",
    )
    resp = sess.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def _text(node: Tag | None) -> str:
    """None セーフな text 取り出し。連続空白を縮める。"""
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _extract_field(card: Tag, label: str) -> str:
    """店舗カード内で、ラベル直後の値テキストを返す。

    サイト側の構造に依存しすぎないよう、ラベル文字列を含む要素を
    見つけて、その次のテキスト兄弟を拾う方針にしている。
    構造が変わったらここを直すのが主な保守ポイント。
    """
    # 店舗カードは dl/dt/dd ではなく div の連続でラベル付けされていることがあるので
    # まずラベル文字を持つ要素を探す
    label_node = card.find(string=re.compile(rf"^\s*{re.escape(label)}\s*$"))
    if not label_node:
        return ""
    parent = label_node.parent
    if parent is None:
        return ""
    # 同じ親の中で、ラベル要素より後ろにある最初のテキスト持ち要素
    sibling = parent.find_next_sibling()
    while sibling is not None and not _text(sibling):
        sibling = sibling.find_next_sibling()
    return _text(sibling)


def parse_region_html(html: str, region_name: str) -> list[Store]:
    """地区ページの HTML から店舗一覧を抽出する。

    サイトは「店舗詳細を見る」リンクを必ず持つので、それを
    店舗カードの目印として使う。リンクの URL スラッグを store_id にする。
    """
    soup = BeautifulSoup(html, "html.parser")
    stores: list[Store] = []

    # 「店舗詳細を見る」リンクを持つ要素を、各店舗カードの代表として拾う
    detail_links = soup.find_all(
        "a", href=re.compile(r"^https?://www\.kaitori-daikichi\.jp/store/[^/]+/?$")
    )
    seen_ids: set[str] = set()

    for link in detail_links:
        detail_url = link.get("href", "")
        # /store/<slug>/ から slug を抜き出す
        m = re.search(r"/store/([^/]+)/?$", detail_url)
        if not m:
            continue
        store_id = m.group(1)
        # 地区インデックス（"kanto" 等）自体のリンクは除外
        if store_id in REGIONS:
            continue
        if store_id in seen_ids:
            continue
        seen_ids.add(store_id)

        # 店舗カードは、リンクを含む祖先のうち、店舗名（strong/h3/h4 等）と
        # 「住所」「営業時間」「定休日」ラベルをまとめて持つ最小ブロック。
        # サイト構造の揺れを吸収するため、いくつかの祖先を試して最も近いものを選ぶ。
        card = _find_card_root(link)
        if card is None:
            continue

        name = _extract_store_name(card)
        if not name:
            continue

        address = _extract_field(card, "住所")
        closed_days = _extract_field(card, "定休日")
        business_hours = _extract_field(card, "営業時間")
        phone = _extract_phone(card)
        map_url = _extract_map_url(card)
        prefecture = _extract_prefecture(address)

        store = Store(
            store_id=store_id,
            name=name,
            region=region_name,
            prefecture=prefecture,
            address=address,
            closed_days=closed_days,
            business_hours=business_hours,
            phone=phone,
            detail_url=urljoin(BASE_URL, detail_url),
            map_url=map_url,
        )
        store.content_hash = store.compute_hash()
        stores.append(store)

    return stores


def _find_card_root(link: Tag) -> Tag | None:
    """「店舗詳細を見る」リンクから、住所等を含む最小の親要素を見つける。

    サイト側は店舗ごとに <article> や <div class="store-card"> 風の
    まとまりがある想定。住所ラベルが現れる最小の祖先を返す。
    """
    cur = link
    for _ in range(8):  # 高さ 8 まで遡れば十分（無限ループ防止）
        parent = cur.parent
        if parent is None:
            return None
        text = parent.get_text(" ", strip=True)
        if "住所" in text and "営業時間" in text:
            return parent
        cur = parent
    return None


def _extract_store_name(card: Tag) -> str:
    """店舗カード内の店舗名を取得する。

    通常は <strong> または見出しタグ。「店舗詳細を見る」「地図を見る」
    のようなリンクテキストは除外する。
    """
    # 1) strong タグを優先
    for tag in card.find_all(["strong", "h3", "h4"]):
        t = _text(tag)
        if t and "店舗詳細" not in t and "地図" not in t:
            return t
    # 2) 見つからなければカード内最初のテキストノード
    return ""


PHONE_RE = re.compile(r"0[\d\-‐ｰ−–—]{8,}")


def _extract_phone(card: Tag) -> str:
    """電話番号を抽出。tel: リンクを優先し、なければテキストから正規表現で。"""
    tel_link = card.find("a", href=re.compile(r"^tel:"))
    if tel_link:
        href = tel_link.get("href", "")
        return href.replace("tel:", "").strip()
    m = PHONE_RE.search(card.get_text(" ", strip=True))
    return m.group(0) if m else ""


def _extract_map_url(card: Tag) -> str:
    """『地図を見る』リンクの URL を取得。Google Maps 短縮URL等が入る。"""
    for a in card.find_all("a"):
        text = _text(a)
        href = a.get("href", "")
        if "地図" in text and href:
            return href
        if "maps.app.goo.gl" in href or "maps.google" in href or "goo.gl/maps" in href:
            return href
    return ""


def _extract_prefecture(address: str) -> str:
    """住所文字列の頭から都道府県を抜き出す。"""
    m = PREFECTURE_RE.match(address.lstrip())
    return m.group(1) if m else ""


def scrape_all(throttle_sec: float = 1.0) -> Iterator[Store]:
    """全地区を順に取得して店舗を yield する。

    サイトに優しくするため、地区ページ間に throttle_sec 秒のスリープを入れる。
    """
    session = requests.Session()
    for slug, region_name in REGIONS.items():
        logger.info("Fetching region: %s (%s)", region_name, slug)
        html = fetch_region_html(slug, session=session)
        stores = parse_region_html(html, region_name)
        logger.info("  parsed %d stores", len(stores))
        for s in stores:
            yield s
        time.sleep(throttle_sec)


def to_dicts(stores: list[Store]) -> list[dict]:
    """シート書き込み用に dict のリストへ変換。"""
    return [asdict(s) for s in stores]
