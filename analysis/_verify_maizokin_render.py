# -*- coding: utf-8 -*-
"""埋蔵金レイヤーの描画・指標セレクト・半径集計(埋蔵金)をヘッドレスChromiumで確認。"""
import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8799/"
LAT = float(sys.argv[2]) if len(sys.argv) > 2 else 35.69
LNG = float(sys.argv[3]) if len(sys.argv) > 3 else 139.70
ZOOM = int(sys.argv[4]) if len(sys.argv) > 4 else 12
INIT = r"""
(() => { let _L;
  const patch=(v)=>{try{if(v&&v.Map&&!v.Map.prototype.__hooked){v.Map.prototype.__hooked=true;
    const o=v.Map.prototype.initialize; v.Map.prototype.initialize=function(...a){window.__map=this;return o.apply(this,a);};}}catch(e){}};
  Object.defineProperty(window,'L',{configurable:true,get(){return _L;},set(v){_L=v;patch(v);}});
})();
"""

def main():
    errors=[]
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True)
        pg=b.new_page(viewport={"width":1280,"height":900})
        pg.add_init_script(INIT)
        pg.on("console", lambda m: errors.append(m.text) if m.type=="error" else None)
        pg.on("pageerror", lambda e: errors.append("PAGEERROR: "+str(e)))
        pg.goto(URL, wait_until="load", timeout=60000)
        pg.wait_for_function("window.__map && window.__map._loaded", timeout=30000)
        pg.evaluate(f"() => {{ window.__map.setView([{LAT},{LNG}], {ZOOM}); return null; }}")
        pg.wait_for_timeout(1200)
        clicked = pg.evaluate(r"""() => {
            const ls=[...document.querySelectorAll('.leaflet-control-layers label')];
            for(const lb of ls){ if(lb.textContent.includes('埋蔵金')){
              const cb=lb.querySelector('input[type=checkbox]'); if(cb&&!cb.checked){cb.click();return true;} return 'already';}}
            return false; }""")
        pg.wait_for_timeout(4000)
        res = pg.evaluate(r"""() => {
            const pane=document.querySelector('.leaflet-maizokin-pane');
            let painted=0, ncanvas=0;
            if(pane){ const cv=pane.querySelectorAll('canvas'); ncanvas=cv.length;
              for(const c of cv){ if(!c.width||!c.height)continue; const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
                for(let i=3;i<d.length;i+=4){ if(d[i]!==0)painted++; } } }
            const sel=document.getElementById('mz-metric');
            const selVisible = sel ? getComputedStyle(sel).display!=='none' : false;
            return {painted, ncanvas, selVisible};
        }""")
        # 半径集計: radiusモード→中心をクリック→結果に埋蔵金が出るか
        pg.evaluate(r"""() => {
            const r=document.querySelector('input[name=clickmode][value=radius]');
            if(r){ r.checked=true; r.dispatchEvent(new Event('change',{bubbles:true})); }
            window.__map.fire('click', {latlng: window.__map.getCenter()});
            return null; }""")
        pg.wait_for_timeout(2500)
        measure = pg.evaluate("() => { const el=document.getElementById('measure-result'); return el? el.innerText : ''; }")
        pg.screenshot(path="analysis/_maizokin_render.png")
        b.close()
    print("URL:", URL)
    print("toggle:", clicked, "| metric select visible:", res.get("selVisible"))
    print("maizokin canvas:", res.get("ncanvas"), "painted px:", res.get("painted"))
    print("measure-result:", repr(measure)[:300])
    print("console errors:", len(errors))
    for e in errors[:8]: print("  -", e[:150])
    ok = res.get("painted",0)>1000 and ('億円' in measure) and not any('PAGEERROR' in e for e in errors)
    print("MAIZOKIN RENDER OK:", ok)
    sys.exit(0 if ok else 1)

if __name__=="__main__":
    main()
