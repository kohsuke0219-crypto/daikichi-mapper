"""なんぼやスクレイパー 実行ラッパー"""
import sys, io, logging
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r"C:\Users\user\Documents\daikichi-mapper")
from scraper.competitors.nanboya import NanboyaScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler()])
log = logging.getLogger("nanboya")
scraper = NanboyaScraper(log=log)
stores = scraper.fetch_stores()
print(f"\n取得完了: {len(stores)} 件")
for s in stores[:5]:
    print(f"  {s['name']} / {s['address']}")
scraper.save(stores, "competitors_nanboya.json")
