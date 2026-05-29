import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pandas as pd

df = pd.read_csv("analysis/score_v4.csv", dtype={"code": str})

print("=== 1. エリアタイプ別 市区町村数 ===")
order = ['超都心','都心住宅','郊外住宅','ロードサイド']
rad = {'超都心':1,'都心住宅':2,'郊外住宅':3,'ロードサイド':5}
for t in order:
    print(f"  {t}（商圏{rad[t]}km）: {len(df[df['area_type']==t])} 市区町村")

print("\n=== 2. スコアv4 トップ20 ===")
cols=['city','pref','area_type','women_40plus','comp_in_radius','location_bonus','score_v4']
top=df.sort_values('score_v4',ascending=False).head(20)
for i,(_,r) in enumerate(top.iterrows(),1):
    print(f"{i:2d}. {r['city']}({r['pref'][:2]}) [{r['area_type']}] "
          f"女40+={int(r['women_40plus']):>7,} 競合{int(r['comp_in_radius']):>2} "
          f"立地×{r['location_bonus']:.2f} v4={r['score_v4']:.1f}")

print("\n=== 3. エリアタイプ別トップ5 ===")
for t in order:
    sub=df[df['area_type']==t].sort_values('score_v4',ascending=False).head(5)
    print(f"\n[{t}]")
    for _,r in sub.iterrows():
        extra = f"駅{int(r['nearest_station_m'])}m" if t in('超都心','都心住宅') else f"道路{int(r['nearest_road_m'])}m"
        print(f"  {r['city']}({r['pref'][:2]}) v4={r['score_v4']:.1f} "
              f"女40+={int(r['women_40plus']):,} 競合{int(r['comp_in_radius'])} {extra}")

print("\n=== 4. v3→v4 順位大変動 トップ10 ===")
df['rank_chg']=df['rank_v3']-df['rank_v4']
print("[UP: v4で評価上昇]")
up=df.sort_values('rank_chg',ascending=False).head(10)
for _,r in up.iterrows():
    print(f"  {r['city']}({r['area_type']}) v3#{int(r['rank_v3'])}→v4#{int(r['rank_v4'])} "
          f"(+{int(r['rank_chg'])}) v4={r['score_v4']:.1f}")
print("[DOWN: v4で評価下落]")
dn=df.sort_values('rank_chg').head(10)
for _,r in dn.iterrows():
    print(f"  {r['city']}({r['area_type']}) v3#{int(r['rank_v3'])}→v4#{int(r['rank_v4'])} "
          f"({int(r['rank_chg'])}) v4={r['score_v4']:.1f}")
