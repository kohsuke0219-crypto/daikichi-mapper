import sys, io, logging
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r"C:\Users\user\Documents\daikichi-mapper")
from scraper.competitors.otakaraya import OtakarayaScraper
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("otakaraya")

scraper = OtakarayaScraper(log=log)

# 東京から1県ずつ取得してコミット（フリーズ対策）
import sys
pref = sys.argv[1] if len(sys.argv) > 1 else None
prefs = [pref] if pref else None

stores = scraper.fetch_stores(prefs)
print(f"\n取得完了: {len(stores)} 件")
for s in stores[:5]:
    print(f"  {s['name'][:30]} lat={s['latitude']} lng={s['longitude']}")

fname = f"competitors_otakaraya_{pref.replace('都','').replace('県','')}.json" if pref else "competitors_otakaraya.json"
scraper.save(stores, fname)
