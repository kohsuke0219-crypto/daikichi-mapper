# -*- coding: utf-8 -*-
"""物件ボード用 商圏マップのスクリーンショットを撮る。
docs/index.html をローカル配信し、各物件の座標へズーム15で寄せ、
買取店マーカー(既存店+競合)＋埋蔵金レイヤーをON、赤マーカーと半径1km(実線)/2km(破線)円を描いてPNG保存。

使い方:
  py analysis/board_screenshot.py                 # 内蔵の19物件を撮影
  py analysis/board_screenshot.py <id> <lat> <lng># 単体（住所ジオコーディングなし）
  py analysis/board_screenshot.py path/to/list.json# [{id,name,address,lat,lng}, ...]
出力: screenshots/board/<id>.png ＋ screenshots/board/centers.json
画像はコミットしない（.gitignore に screenshots/）。
"""
import json, sys, re, time, subprocess, threading, http.server, socketserver, functools, urllib.parse, urllib.request
from pathlib import Path

BASE = Path(__file__).parent
ROOT = BASE.parent
DOCS = ROOT / "docs"
OUTDIR = ROOT / "screenshots" / "board"
PORT = 8765
ZOOM = 16   # 既定ズーム（--zoom で変更可）

# 内蔵19物件 (id, 物件名, 住所, lat, lng)
ROWS = [
 ("hotinfo-36735","Villa Riso Eifuku 1階（新築）","東京都杉並区永福2丁目51-13",35.676225,139.64267),
 ("itenpo-t100377","水天宮前駅 徒歩3分 11.01坪 1階","",35.683001,139.785171),
 ("td-306-04","横浜市旭区鶴ヶ峰2丁目 9.52坪 1階","神奈川県横浜市旭区鶴ヶ峰2丁目",35.47509,139.549985),
 ("td-chitosefunabashi","世田谷区船橋1丁目8-10 6.05坪 1階","東京都世田谷区船橋1丁目8-10",35.647675,139.62453),
 ("td-ichinoe","江戸川区江戸川4丁目 6.95坪 1階","東京都江戸川区江戸川4丁目",35.68594,139.88289),
 ("td-ningyocho","中央区日本橋堀留町1丁目8-6 10.91坪 1階","東京都中央区日本橋堀留町1丁目8-6",35.686259,139.782338),
 ("td-nogata","中野区野方1丁目 11.91坪 1階","東京都中野区野方1丁目",35.70574,139.665605),
 ("td-shimoochiai","新宿区下落合4丁目 13.08坪 1階","東京都新宿区下落合4丁目",35.715692,139.6953),
 ("ts-220499","三ツ境駅 徒歩1分 8.75坪 1階","",35.467785,139.50257),
 ("ts-220516","池ノ上駅 徒歩1分 9.07坪 1階","",35.66037,139.673455),
 ("ts-220536","江戸川橋駅 徒歩1分 8.83坪 1階","",35.709295,139.73413),
 ("ts-220555","西台駅 徒歩1分 8.51坪 1階","",35.78708,139.67268),
 ("ts-220567","西巣鴨駅 徒歩1分 9.79坪 1階","",35.743415,139.728725),
 ("ts-220582","茗荷谷駅 徒歩6分 11.34坪 1階","",35.7172,139.736895),
 ("ts-220632","田町駅 徒歩8分 13.13坪 1階","",35.64574,139.747605),
 ("ts-220700","保谷駅 徒歩2分 10.28坪 1階","",35.748242,139.568035),
 ("yousen-itabashi","小泉ビル 1階一部分","東京都板橋区板橋1-54-2",35.746433,139.721008),
 ("yousen-kaminoge","プラスリノ上野毛 101","東京都世田谷区上野毛1-17-11",35.61282,139.639771),
 ("yousen-morishita","サクシード森下 1階","東京都江東区森下1-14-8",35.688648,139.798065),
]

def has_banchi(addr):
    # 「丁目」より細かい番地(数字-数字)が含まれるか
    return bool(re.search(r"\d\s*[-−ー]\s*\d", addr))

def gsi_geocode(q):
    url = "https://msearch.gsi.go.jp/address-search/AddressSearch?q=" + urllib.parse.quote(q)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
        if d:
            c = d[0]["geometry"]["coordinates"]  # [lng,lat]
            return float(c[1]), float(c[0])
    except Exception as e:
        print(f"  [gsi失敗] {q}: {e}")
    return None

def resolve_center(row):
    _id, name, addr, lat, lng = row
    if addr and has_banchi(addr):
        g = gsi_geocode(addr)
        if g:
            return {"lat": round(g[0],6), "lng": round(g[1],6), "basis": "住所"}
    if addr:
        return {"lat": lat, "lng": lng, "basis": "住所(丁目)"}
    return {"lat": lat, "lng": lng, "basis": "駅"}

def start_server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DOCS))
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd

INIT = r"""
(() => { let _L;
  const patch=(v)=>{try{if(v&&v.Map&&!v.Map.prototype.__hooked){v.Map.prototype.__hooked=true;
    const o=v.Map.prototype.initialize; v.Map.prototype.initialize=function(...a){window.__map=this;return o.apply(this,a);};}}catch(e){}};
  Object.defineProperty(window,'L',{configurable:true,get(){return _L;},set(v){_L=v;patch(v);}});
})();
"""

HIDE_CSS = """
.leaflet-control-container { display:none !important; }
#choropleth-select, #own-brand, #flow-metric, #mz-metric, #bg-status { display:none !important; }
/* 店舗マーカーを少し大きめに（買取大吉/おたからや/なんぼや/バイセル/リプセル等） */
.leaflet-daikichi-pane .shape-pin { transform: scale(1.5); }
.leaflet-stores-pane circle { r: 6; }
"""

SET_LAYERS = r"""
() => {
  // 撮影に写すもの: 既存店・競合(リプセル含む)・人流(緑線)。埋蔵金は表示しない。
  const want = { on: ['既存店','競合店','人流（通り別'],
                 off: ['埋蔵金','道路の通行量','生活動線','女性向け生活','新規オープン','市区町村の役所','駅（1日'] };
  const labels = [...document.querySelectorAll('.leaflet-control-layers label')];
  const setState = (needle, on) => {
    for (const lb of labels){ if (lb.textContent.includes(needle)){
      const cb = lb.querySelector('input[type=checkbox]');
      if (cb && cb.checked !== on) cb.click();
      return; } }
  };
  want.on.forEach(n => setState(n, true));
  want.off.forEach(n => setState(n, false));
  // ベースのコロプレス(女性人口)は非表示にして商圏図をすっきりさせる
  const sel = document.getElementById('choropleth-select');
  if (sel && sel.value !== 'none'){ sel.value='none'; sel.dispatchEvent(new Event('change',{bubbles:true})); }
  return true;
}
"""

def marker_js(lat, lng):
    return f"""
    () => {{
      const L = window.L, map = window.__map;
      if (window.__mk) window.__mk.forEach(l => map.removeLayer(l));
      const icon = L.divIcon({{ className:'', iconSize:[30,42], iconAnchor:[15,42],
        html:'<svg width=30 height=42 viewBox="0 0 30 42"><path d="M15 0C6.7 0 0 6.7 0 15c0 11 15 27 15 27s15-16 15-27C30 6.7 23.3 0 15 0z" fill="#e11d1d" stroke="#fff" stroke-width="2"/><circle cx="15" cy="15" r="5.5" fill="#fff"/></svg>' }});
      const m = L.marker([{lat},{lng}], {{ icon, zIndexOffset:10000 }});
      const c1 = L.circle([{lat},{lng}], {{ radius:500,  color:'#e11d1d', weight:3.5, opacity:0.95, fill:false }});
      const c2 = L.circle([{lat},{lng}], {{ radius:1000, color:'#e11d1d', weight:2,   opacity:0.9,  dashArray:'9,7', fill:false }});
      [c1,c2,m].forEach(l => l.addTo(map));
      window.__mk = [c1,c2,m];
      return true;
    }}
    """

def main():
    global ZOOM
    args = sys.argv[1:]
    # --zoom N（既定16）
    if "--zoom" in args:
        i = args.index("--zoom"); ZOOM = int(args[i+1]); del args[i:i+2]

    OUTDIR.mkdir(parents=True, exist_ok=True)
    cpath = OUTDIR / "centers.json"
    centers = {}
    if cpath.exists():
        try: centers = json.loads(cpath.read_text(encoding="utf-8"))
        except Exception: centers = {}

    reshoot = False
    if len(args) == 3:
        rows = [(args[0], args[0], "", float(args[1]), float(args[2]))]
    elif len(args) == 1 and args[0].endswith(".json"):
        data = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        rows = [(d["id"], d.get("name",d["id"]), d.get("address",""), float(d["lat"]), float(d["lng"])) for d in data]
    elif centers:
        # 引数なし: centers.json の全物件を保存済み座標のまま撮り直す（再ジオコーディングしない）
        reshoot = True
        rows = [(k, k, "", v["lat"], v["lng"]) for k, v in centers.items()]
    else:
        rows = ROWS

    if not reshoot:
        for r in rows:
            centers[r[0]] = resolve_center(r)
        cpath.write_text(json.dumps(centers, ensure_ascii=False, indent=1), encoding="utf-8")

    httpd = start_server()
    saved, failed = [], []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            pg = b.new_page(viewport={"width":1280,"height":960})
            pg.add_init_script(INIT)
            errors=[]
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(f"http://127.0.0.1:{PORT}/", wait_until="load", timeout=60000)
            pg.wait_for_function("window.__map && window.__map._loaded", timeout=30000)
            pg.add_style_tag(content=HIDE_CSS)
            pg.evaluate(SET_LAYERS)
            pg.wait_for_timeout(1000)
            for r in rows:
                _id = r[0]; c = centers[_id]
                try:
                    pg.evaluate(f"() => {{ window.__map.setView([{c['lat']},{c['lng']}], {ZOOM}); return null; }}")
                    # 店舗マーカー・人流(緑線)タイルの範囲追随ロードを促す（埋蔵金は表示しない）
                    pg.evaluate(SET_LAYERS)
                    try: pg.wait_for_load_state("networkidle", timeout=8000)
                    except Exception: pass
                    # 人流(緑線)タイルは描画完了まで数秒かかるため固定待機（早期打ち切りで未描画になるのを防ぐ）
                    pg.wait_for_timeout(6500)
                    PP = """() => { const pane=document.querySelector('.leaflet-pedflow-pane'); if(!pane) return 0; const c=pane.querySelector('canvas'); if(!c||!c.width) return 0; const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data; let n=0; for(let i=3;i<d.length;i+=4) if(d[i]!==0) n++; return n; }"""
                    # 未描画なら中心を取り直して再ロード（最大2回）
                    for _ in range(2):
                        if pg.evaluate(PP) > 0: break
                        pg.evaluate(f"() => {{ window.__map.setView([{c['lat']+0.0008},{c['lng']}], {ZOOM}); window.__map.setView([{c['lat']},{c['lng']}], {ZOOM}); return null; }}")
                        pg.wait_for_timeout(5000)
                    if pg.evaluate(PP) <= 0:
                        print(f"    [警告] {_id}: 人流(緑線)が描画されませんでした")
                    pg.evaluate(marker_js(c['lat'], c['lng']))
                    pg.wait_for_timeout(1200)
                    pg.screenshot(path=str(OUTDIR / f"{_id}.png"))
                    saved.append(_id)
                    print(f"  saved {_id} @ {c['lat']},{c['lng']} ({c['basis']})")
                except Exception as e:
                    failed.append((_id, str(e)[:80]))
                    print(f"  [失敗] {_id}: {e}")
            b.close()
            if errors: print("pageerrors:", errors[:3])
    finally:
        httpd.shutdown()
    print(f"\n保存 {len(saved)}枚 / 失敗 {len(failed)}枚")
    if failed: print("失敗id:", failed)
    print("centers.json:", OUTDIR / "centers.json")

if __name__ == "__main__":
    main()
