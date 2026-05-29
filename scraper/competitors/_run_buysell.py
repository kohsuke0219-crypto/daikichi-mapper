import sys, io, logging
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r"C:\Users\user\Documents\daikichi-mapper")
from scraper.competitors.buysell import BuysellScraper
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
scraper = BuysellScraper(log=logging.getLogger("buysell"))
stores = scraper.fetch_stores()
print(f"\n取得完了: {len(stores)} 件")
for s in stores[:5]:
    print(f"  {s['name']} / {s['address'][:50]} / lat={s['latitude']}")
scraper.save(stores, "competitors_buysell.json")
