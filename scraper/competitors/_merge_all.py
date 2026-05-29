import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from pathlib import Path

all_c = []
for brand, fname in [
    ('なんぼや',  'competitors_nanboya.json'),
    ('バイセル',  'competitors_buysell.json'),
    ('おたからや','competitors_otakaraya.json'),
]:
    data = json.loads(Path(f'docs/data/{fname}').read_text(encoding='utf-8'))
    valid = [s for s in data if s.get('latitude') and s.get('longitude')]
    print(f'{brand}: 全{len(data)}件 → 座標あり{len(valid)}件')
    all_c.extend(valid)

out = Path('docs/data/competitors_all.json')
out.write_text(json.dumps(all_c, ensure_ascii=False, separators=(',',':')), encoding='utf-8')
print(f'合計: {len(all_c)}件 → {out.name} ({out.stat().st_size//1024}KB)')
