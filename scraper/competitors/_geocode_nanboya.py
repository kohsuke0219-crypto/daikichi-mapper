"""なんぼや 82件のジオコーディング（Google Maps API）"""
import sys, io, json, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r"C:\Users\user\Documents\daikichi-mapper")

from pathlib import Path
from scraper.geocoder import Geocoder

# 環境変数をset_env.ps1から読む
env_file = Path(r"C:/Users/user/Documents/daikichi-secrets/set_env.ps1")
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "GOOGLE_MAPS_API_KEY" in line and "=" in line:
            key = line.split("=",1)[1].strip().strip('"').strip("'")
            os.environ["GOOGLE_MAPS_API_KEY"] = key
            print(f"API KEY loaded: {key[:10]}...")
            break

DATA_PATH = Path("docs/data/competitors_nanboya.json")
data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
print(f"なんぼや: {len(data)}件")

geocoder = Geocoder(throttle_sec=0.1)
updated = 0
failed = []

for i, store in enumerate(data):
    if store.get("latitude") is not None:
        continue
    addr = store.get("address","").strip()
    if not addr:
        failed.append(store["name"])
        continue

    result = geocoder.geocode(addr)
    if result.latitude:
        store["latitude"] = result.latitude
        store["longitude"] = result.longitude
        updated += 1
        print(f"  [{i+1:2d}] {store['name'][:25]:25s} → {result.latitude:.4f}, {result.longitude:.4f}")
    else:
        failed.append(store["name"])
        print(f"  [{i+1:2d}] {store['name'][:25]:25s} → FAILED ({result.status})")

print(f"\n完了: 成功{updated}件 失敗{len(failed)}件")
if failed:
    print(f"失敗: {failed}")

DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"保存: {DATA_PATH}")
