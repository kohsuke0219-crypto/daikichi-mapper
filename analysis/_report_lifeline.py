import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pandas as pd
from pathlib import Path

data = json.loads(Path("docs/data/lifeline_stores.json").read_text(encoding="utf-8"))
df = pd.DataFrame(data)
print(f"総数: {len(df)}")
print("\n=== 業態別 × 都県別 ===")
pv = df.pivot_table(index="prefecture", columns="category", values="name", aggfunc="count", fill_value=0)
pv["合計"] = pv.sum(axis=1)
pv.loc["合計"] = pv.sum()
print(pv.to_string())
print("\n=== チェーン別 ===")
print(df.groupby(["category","chain"]).size().sort_values(ascending=False).to_string())
