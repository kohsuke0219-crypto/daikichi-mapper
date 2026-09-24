# -*- coding: utf-8 -*-
"""物件掲載ページ（公開・ログイン不要の範囲）から物件写真を取得する。
- 1物件最大4枚。優先: 外観→内観→写真。図面は1枚まで（写真が無い時の代替）。
- 広告バナー・ロゴ・地図・ログイン要プレースホルダは除外。
- 保存: screenshots/board/photos/<id>-<n>.jpg（長辺1600px以内）。一覧 photos.json に追記。
- 取得できない物件は空配列で記録（ログイン必須サイトなど）。

使い方:
  py analysis/board_photos.py                 # 内蔵25物件
  py analysis/board_photos.py <id> <url>      # 単体
  py analysis/board_photos.py list.json       # [{id,url}, ...]
画像は screenshots/ 配下（.gitignore）でコミットしない。
"""
import json, sys, re, io
from pathlib import Path

BASE = Path(__file__).parent
OUTDIR = BASE.parent / "screenshots" / "board" / "photos"
MANIFEST = OUTDIR / "photos.json"
MAXW = 1600

ROWS = [
 ("ts-220030","https://www.temposmart.jp/estates/220030"),
 ("ts-220499","https://www.temposmart.jp/estates/220499"),
 ("ts-220507","https://www.temposmart.jp/estates/220507"),
 ("ts-220516","https://www.temposmart.jp/estates/220516"),
 ("ts-220529","https://www.temposmart.jp/estates/220529"),
 ("ts-220536","https://www.temposmart.jp/estates/220536"),
 ("ts-220537","https://www.temposmart.jp/estates/220537"),
 ("ts-220555","https://www.temposmart.jp/estates/220555"),
 ("ts-220556","https://www.temposmart.jp/estates/220556"),
 ("ts-220567","https://www.temposmart.jp/estates/220567"),
 ("ts-220582","https://www.temposmart.jp/estates/220582"),
 ("ts-220630","https://www.temposmart.jp/estates/220630"),
 ("ts-220632","https://www.temposmart.jp/estates/220632"),
 ("ts-220638","https://www.temposmart.jp/estates/220638"),
 ("ts-220675","https://www.temposmart.jp/estates/220675"),
 ("ts-220691","https://www.temposmart.jp/estates/220691"),
 ("ts-220699","https://www.temposmart.jp/estates/220699"),
 ("ts-220700","https://www.temposmart.jp/estates/220700"),
 ("ts-220741","https://www.temposmart.jp/estates/220741"),
 ("ts-220761","https://www.temposmart.jp/estates/220761"),
 ("itenpo-t100377","https://www.i-tenpo.com/t100377"),
 ("itenpo-t102587","https://www.i-tenpo.com/t102587"),
 ("itenpo-t99523","https://www.i-tenpo.com/t99523"),
 ("td-306-02","https://tempodas.com/tenant/real_estate/936203"),
 ("td-306-04","https://tempodas.com/tenant/real_estate/936285"),
]

EXCLUDE = ["nologin","logo","banner","/map","googlemap","sprite","icon","common","btn",
           "loading","ogp","sample","placeholder","recruit","noimage","no_image","dummy",".svg"]

def classify(caption):
    c = (caption or "")
    if any(k in c for k in ["外観","建物外","ファサード"]): return "外観"
    if any(k in c for k in ["間取","図面","平面図","レイアウト"]): return "図面"
    if any(k in c for k in ["客席","店内","内装","厨房","内観","室内","フロア","カウンター"]): return "内観"
    return "写真"

def collect(pg, url):
    """ページから候補写真URL（大きい実写真のみ）を優先順で返す。"""
    import re as _re
    eid_m = _re.search(r"(\d{4,})", url); eid = eid_m.group(1) if eid_m else ""
    seen = []
    def add(u, cap=""):
        if not u or u.startswith("data:"): return
        lu = u.lower()
        if any(k in lu for k in EXCLUDE): return
        if u not in [s[0] for s in seen]: seen.append((u, cap))
    host = ""
    try: host = _re.sub(r"^https?://([^/]+)/.*$", r"\1", url)
    except Exception: pass
    # <img> で十分大きいもの（naturalサイズ）
    imgs = pg.evaluate("""()=>[...document.querySelectorAll('img')].map(i=>({src:i.currentSrc||i.src, alt:(i.alt||i.title||''), w:i.naturalWidth, h:i.naturalHeight}))""")
    # サイト別の実写真パターンを優先
    for x in imgs:
        s = x["src"] or ""
        if "img.i-tenpo.com/loader/tenpo/get" in s and x["w"] >= 500 and x["h"] >= 350:
            add(s, x["alt"])
    if eid:
        for x in imgs:
            s = x["src"] or ""
            if "thumbnail.temposmart.jp" in s and f"/estates/{eid}/" in s and x["w"] >= 300:
                add(s, x["alt"])
    # 汎用: 大きい写真
    for x in imgs:
        if x["w"] >= 640 and x["h"] >= 420:
            add(x["src"], x["alt"])
    return eid, seen

def save_photos(pg, _id, cands):
    from PIL import Image
    photos = []
    n = 0
    drawings = 0
    for url, cap in cands:
        if n >= 4: break
        kind = classify(cap)
        if kind == "図面" and drawings >= 1: continue
        try:
            resp = pg.request.get(url, timeout=30000)
            if not resp.ok: continue
            data = resp.body()
            if len(data) < 6000: continue   # 極小はアイコン等
            im = Image.open(io.BytesIO(data)).convert("RGB")
            if max(im.size) > MAXW:
                r = MAXW / max(im.size)
                im = im.resize((int(im.size[0]*r), int(im.size[1]*r)))
            if min(im.size) < 200: continue  # 小さすぎる装飾は除外
            n += 1
            fn = f"{_id}-{n}.jpg"
            im.save(OUTDIR / fn, "JPEG", quality=85)
            if kind == "図面": drawings += 1
            photos.append({"file": fn, "kind": kind, "caption": (cap or "").strip()[:60]})
        except Exception as e:
            print(f"    [dl失敗] {url[:70]}: {str(e)[:50]}")
    # 図面のみで写真がある場合の優先は collect 側の順序に委ねる（外観/内観優先はcaption分類で担保）
    photos.sort(key=lambda p: {"外観":0,"内観":1,"写真":2,"図面":3}[p["kind"]])
    return photos

def main():
    args = sys.argv[1:]
    if len(args) == 2 and not args[0].endswith(".json"):
        rows = [(args[0], args[1])]
    elif len(args) == 1 and args[0].endswith(".json"):
        rows = [(d["id"], d["url"]) for d in json.loads(Path(args[0]).read_text(encoding="utf-8"))]
    else:
        rows = ROWS
    OUTDIR.mkdir(parents=True, exist_ok=True)
    manifest = {}
    if MANIFEST.exists():
        try: manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception: manifest = {}

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width":1400,"height":1200}, user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"))
        pg = ctx.new_page()
        for _id, url in rows:
            try:
                pg.goto(url, wait_until="networkidle", timeout=45000)
                pg.mouse.wheel(0, 2500); pg.wait_for_timeout(1800)
                eid, cands = collect(pg, url)
                photos = save_photos(pg, _id, cands) if cands else []
                manifest[_id] = photos
                print(f"  {_id}: {len(photos)}枚  ({'/'.join(p['kind'] for p in photos) or '公開写真なし'})")
            except Exception as e:
                manifest[_id] = manifest.get(_id, [])
                print(f"  [失敗] {_id}: {str(e)[:70]}")
        b.close()
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    got = sum(1 for v in manifest.values() if v)
    total = sum(len(v) for v in manifest.values())
    print(f"\n写真あり物件 {got} / 総枚数 {total}  -> {MANIFEST}")

if __name__ == "__main__":
    main()
