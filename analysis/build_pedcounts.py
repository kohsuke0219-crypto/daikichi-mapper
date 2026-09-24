# -*- coding: utf-8 -*-
"""実測（自治体の歩行者通行量調査）を統合し docs/data/pedestrian_counts.json を生成。
- 町田(2018)・厚木(R6) は公式Excelを直接パース（一時DL済み）。
- 八王子(R5)・小田原(R7)・相模原(R4) はPDF出典の地点別実数（値は原典と照合済み）。
- 地点を国土地理院ジオコーダ(無料・ログイン不要)で緯度経度化。precisionを付与。
出典PDF/Excelはリポジトリに含めない。"""
import json, time, urllib.parse, urllib.request, math, re
from pathlib import Path
import pandas as pd

BASE = Path(__file__).parent
OUT = BASE.parent / "docs" / "data" / "pedestrian_counts.json"
TMP = Path("C:/Users/user/AppData/Local/Temp/pedcounts")

SRC_HACHIOJI = "https://www.city.hachioji.tokyo.jp/kurashi/sangyo/003/004/p014345_d/fil/R5houkokusyo.pdf"
SRC_MACHIDA  = "https://www.city.machida.tokyo.jp/shisei/opendata/sangyo/tsukouryouchousa.html"
SRC_ODAWARA  = "https://www.city.odawara.kanagawa.jp/field/industry/urban/ryudokyaku.html"
SRC_SAGAMI   = "https://www.city.sagamihara.kanagawa.jp/_res/projects/default_project/_page_/001/003/391/r04_digest.pdf"
SRC_ATSUGI   = "https://www.city.atsugi.kanagawa.jp/soshiki/shogyonigiwaika/3/29346.html"
SRC_KUMAGAYA = "https://www.city.kumagaya.lg.jp/about/boshu/ikenkoubo/kekaanken/tyuukatsu_kouhyou.files/all_tyukatu.pdf"

# ---- 熊谷市 平成24年(2012) 中心市街地活性化基本計画p.78 地点別（休日・10-19時=9h・歩行者+自転車合算）old ----
KUMAGAYA = [
 ("①国道17号北側(埼玉縣信用金庫本店前)","熊谷市 国道17号 埼玉縣信用金庫熊谷本店",1756),
 ("②鎌倉町商店街(日進パレステージ熊谷鎌倉町)","熊谷市鎌倉町 鎌倉町商店街",1271),
 ("③星川通線北側歩道(岡田ミシン商会前)","熊谷市 星川通り",473),
 ("④埼玉りそな銀行熊谷駅前支店前","熊谷市 埼玉りそな銀行熊谷駅前支店",1448),
 ("⑤熊谷停車場線東側歩道(栗原弁天堂ビル前)","熊谷市 熊谷駅 熊谷停車場線",1746),
 ("⑥熊谷駅東口線(ティアラ21前)","熊谷市筑波 ティアラ21 熊谷駅東口",6383),
 ("⑦駅西通り商店街北側歩道(理容下山前)","熊谷市 駅西通り商店街",1029),
 ("⑧駅西通り商店街南側歩道(李家前)","熊谷市 駅西通り商店街",1577),
 ("⑨星川通線北側歩道(福乃家前)","熊谷市 星川通り",682),
 ("⑩国道17号北側・南側歩道(天沼洋品店前)","熊谷市 国道17号",460),
]
SRC_KAWAGOE = "https://www.chisou.go.jp/tiiki/chukatu/pdf_nintei/171_kawagoesi_full.pdf"
SRC_KASUKABE = "https://www.city.kasukabe.lg.jp/material/files/group/41/toshisaiseihennkou2.pdf"
SRC_SAITAMA  = "https://www.city.saitama.lg.jp/001/010/018/007/002/p005496.html"

# ---- さいたま市 令和3年(2021) 道路交通センサス歩行者系（昼間12時間・上下合計・歩行者/自転車分離）covid ----
SAITAMA = [  # (地点名, ジオコーディング用住所, 歩行者数, 自転車台数)
 ("大宮区大門町1丁目32(大宮停車場線)","さいたま市大宮区大門町1丁目32",22389,512),
 ("大宮区桜木町1丁目11-3(三橋中央通線)","さいたま市大宮区桜木町1丁目11-3",9707,2955),
 ("大宮区下町1丁目6番地先","さいたま市大宮区下町1丁目6",7624,1348),
 ("大宮区桜木町1丁目8-4","さいたま市大宮区桜木町1丁目8-4",6313,1456),
 ("大宮区下町2丁目4","さいたま市大宮区下町2丁目4",5605,1645),
 ("大宮区桜木町2丁目303(大宮停車場大成線)","さいたま市大宮区桜木町2丁目303",4042,1214),
 ("大宮区吉敷町4丁目267(けやき通東線)","さいたま市大宮区吉敷町4丁目267",3195,2031),
 ("大宮区吉敷町4丁目107番地先","さいたま市大宮区吉敷町4丁目107",2223,1939),
 ("大宮区宮町1丁目28","さいたま市大宮区宮町1丁目28",2107,3364),
 ("浦和区北浦和4丁目3-18(北浦和停車場線)","さいたま市浦和区北浦和4丁目3-18",7213,1116),
 ("浦和区仲町1丁目4-9","さいたま市浦和区仲町1丁目4-9",6169,2511),
 ("浦和区上木崎2丁目14-14(上木崎与野停車場線)","さいたま市浦和区上木崎2丁目14-14",4201,2385),
 ("浦和区東高砂町19番地5先(さいたま草加線)","さいたま市浦和区東高砂町19",3707,4759),
 ("浦和区北浦和1丁目21-16(さいたま幸手線)","さいたま市浦和区北浦和1丁目21-16",3436,3234),
 ("浦和区本太2丁目8-17","さいたま市浦和区本太2丁目8-17",2705,3061),
 ("浦和区高砂3丁目16-45","さいたま市浦和区高砂3丁目16-45",2091,1055),
]

# ---- 川越市 平成26年(2014)5/25 中心市街地活性化基本計画p.36（休日・10-19時=9h・歩行者+自転車合算）old ----
KAWAGOE = [
 ("H・太陽ビル前","川越市 クレアモール",37210),
 ("I・東和銀行川越支店前","川越市 クレアモール 東和銀行川越支店",34354),
 ("Q・やまわ前","川越市幸町 一番街 蔵造りの町並み",23660),
 ("P・鍛冶町広場前","川越市 一番街 鍛冶町広場",19466),
 ("O・小江戸蔵里前","川越市新富町 小江戸蔵里",15586),
 ("G・イトーヨーカドー前","川越市 イトーヨーカドー川越店",14822),
 ("C・田中製帽店前","川越市 クレアモール",13966),
 ("E・吉野園前","川越市 クレアモール",13154),
 ("T・大正浪漫夢通り","川越市連雀町 大正浪漫夢通り",12922),
 ("D・ローソンショップ前","川越市 クレアモール",11764),
 ("R・菓子屋横丁","川越市元町 菓子屋横丁",11628),
 ("B・桜井ビル前","川越市 本川越駅",9566),
 ("J・グランベルビル前","川越市 クレアモール",9088),
 ("A・イーグルトラベル前","川越市 川越駅",6444),
 ("L・川越駅前ビル前","川越市 川越駅前",6294),
 ("K・堺屋金物店前","川越市仲町 中央通り",5968),
 ("M・埼玉りそな銀行川越南支店前","川越市 川越駅",5144),
 ("N・川越駅西口歩行者デッキ","川越市 川越駅西口",4608),
]

# ---- 八王子市 令和5年度(2023) 中心市街地歩行量調査（平日・9-22時=13h・歩行者のみ）----
HACHIOJI = [
 ("東放射線アイロード①","八王子駅北口 東放射線アイロード",16883),
 ("東放射線アイロード②","八王子駅北口 東放射線アイロード",4791),
 ("八王子駅北口交番前","八王子駅北口 交番前",45114),
 ("ドン・キホーテ前","八王子市 ドン・キホーテ八王子駅前店",18355),
 ("横山町公園","八王子市横山町 横山町公園",8324),
 ("八王子駅入口交差点","八王子駅入口交差点",4052),
 ("甲州街道①","八王子市 甲州街道 国道20号",2281),
 ("甲州街道②","八王子市 甲州街道 国道20号",1852),
 ("八日町交差点","八王子市 八日町交差点",2942),
 ("甲州街道③","八王子市 甲州街道 国道20号",2647),
 ("甲州街道④","八王子市八幡町 甲州街道",2766),
 ("とちの木デッキ下","八王子駅北口 とちの木デッキ",26186),
 ("八王子駅北口通路①","八王子駅北口 ペデストリアンデッキ",79301),
 ("八王子駅北口通路②","八王子駅北口 ペデストリアンデッキ",34129),
 ("八王子駅南口通路","八王子駅南口 ペデストリアンデッキ",60090),
 ("三井住友銀行前","八王子市 三井住友銀行八王子支店",26742),
 ("京王八王子駅中央口","京王八王子駅 中央口",19677),
 ("桑並木通り","八王子市 桑並木通り",6579),
 ("八王子スクエアビル南","八王子市 八王子スクエアビル",6258),
 ("八王子スクエアビル西①","八王子市 八王子スクエアビル",7405),
 ("八王子スクエアビル西②","八王子市 八王子スクエアビル",3759),
 ("八王子スクエアビル北","八王子市 八王子スクエアビル",7860),
 ("パーク壱番街通り①","八王子市 パーク壱番街",2073),
 ("パーク壱番街通り②","八王子市 パーク壱番街",3446),
 ("マルベリーブリッジ","八王子駅北口 マルベリーブリッジ",43041),
 ("甲州街道⑤","八王子市八幡町 甲州街道",1728),
 ("富士見通り","八王子市 富士見通り",5127),
 ("みさき通り","八王子市 みさき通り",2871),
 ("ジョイ五番街通り","八王子市 ジョイ五番街",3383),
 ("みずき通り","八王子市 みずき通り",1470),
 ("野猿街道","八王子市 野猿街道",3102),
 ("とちの木通り","八王子市 とちの木通り",2834),
]

# ---- 小田原市 第81回(令和7/2025) 主要商店街流動客調査（土・12-18時=6h・歩行者）----
ODAWARA = [
 ("東通り・HaRuNe出入口前","小田原市栄町 東通り",6687),
 ("おしゃれ横丁・いいだ裏","小田原市 おしゃれ横丁",2089),
 ("錦通り・北條ポケットパーク前","小田原市 錦通り",8653),
 ("駅前通り・かごせい前","小田原市栄町 駅前通り",5378),
 ("錦通り・昇玉・メガネスーパー前","小田原市 錦通り",3179),
 ("錦通り・横浜銀行小田原支店前","小田原市 錦通り 横浜銀行小田原支店",10277),
 ("錦通り・小田原おしりとおなかのクリニック前","小田原市 錦通り",4340),
 ("ダイヤ街・錦通り側入口","小田原市 小田原ダイヤ街",6840),
 ("ダイヤ街・りそな銀行横","小田原市 小田原ダイヤ街 りそな銀行",3733),
 ("銀座通り・フレンチ食堂iTToku前","小田原市 銀座通り",1719),
 ("銀座通り・銀座会館前","小田原市 銀座通り",689),
 ("竹の花通り・くまきん前","小田原市 竹の花通り",1149),
 ("中央通り・和の燻製小田原駅前店前","小田原市栄町 中央通り",2064),
 ("中央通り・鳥ぎん前","小田原市栄町 中央通り",1535),
 ("緑一番街・松下靴店前","小田原市 緑一番街",2042),
 ("緑一番街・ル・サンク小田原栄町入口前","小田原市栄町 緑一番街",3160),
 ("大工町通り・ダイレクトパーク駐車場前","小田原市 大工町",1830),
 ("お城通り・鈴廣小田原駅前店前","小田原市栄町 お城通り",13606),
 ("銀座通り・二宮呉服店前","小田原市 銀座通り",703),
 ("万葉の湯横・金時前","小田原市栄町 万葉の湯",2266),
 ("小田原浜町線・ジャンボーナックビル横","小田原市浜町 小田原浜町線",2662),
 ("小田原浜町線・さがみ信金駅前支店前","小田原市浜町 小田原浜町線",2738),
 ("お堀端通り・オダキューOX前","小田原市 お堀端通り オダキューOX",4960),
 ("お堀端通り・アジアンギャラリー山帰来前","小田原市 お堀端通り",5025),
 ("小田原不動産前","小田原市栄町 小田原駅周辺",1688),
 ("うらちょう・小田原年金事務所前","小田原市浜町 小田原年金事務所",480),
 ("青物町・松崎屋陶器店前","小田原市青物町",640),
 ("ハルネ小田原","小田原市栄町 ハルネ小田原",10925),
]

# ---- 相模原市 令和4年度(2022) 商業実態調査（日・10-20時=10h・歩行者/中学生以上）----
SAGAMI = [
 ("イオン出入口","相模原市緑区橋本 イオン橋本",11034),
 ("ビーズモール前","相模原市緑区橋本 ビーズモール",4856),
 ("CHALLENGER前","相模原市緑区橋本",7637),
 ("ミウィ出入口","相模原市緑区橋本 ミウィ橋本",19093),
 ("ミウィ横","相模原市緑区橋本 ミウィ橋本",4708),
 ("HK第4ビル前","相模原市緑区橋本",6897),
 ("きらぼし銀行橋本支店前","相模原市緑区橋本 きらぼし銀行橋本支店",2449),
 ("Okazaki BLD前","相模原市緑区橋本",2439),
 ("第一商事前","相模原市緑区橋本",1209),
 ("橋本駅南口階段前","相模原市緑区橋本 橋本駅南口",8544),
 ("やすらぎの道立体上","相模原市緑区橋本",10733),
 ("カネコ時計店前","相模原市中央区相模原 相模原駅前",1349),
 ("エイブル前","相模原市中央区相模原 相模原駅前",1864),
 ("パチンコプラザ相模原前","相模原市中央区相模原",5050),
 ("T'S BRIGHTIA前","相模原市中央区相模原",3925),
 ("ツカサビル前","相模原市中央区相模原",1354),
 ("スポーツクラブS・C相模原前","相模原市中央区相模原",2306),
 ("セブンイレブン相模原5丁目店前","相模原市中央区相模原5丁目",2025),
 ("ロビーファイブ前","相模原市南区相模大野 相模大野駅前",3117),
 ("プラザシティ相模大野前","相模原市南区相模大野",2288),
 ("ボーノ前","相模原市南区相模大野 ボーノ相模大野",27179),
 ("大野銀座入口","相模原市南区相模大野 大野銀座",5342),
 ("エピカビル横","相模原市南区相模大野",1404),
 ("au前","相模原市南区相模大野",8945),
 ("コリドー入口","相模原市南区相模大野 コリドー",9014),
 ("季節の橋下","相模原市南区相模大野",4007),
 ("くすりPaseos前","相模原市南区相模大野",7394),
 ("しんしん亭前","相模原市南区相模大野",2182),
 ("SWEETS O'CLOCK前","相模原市南区相模大野",8688),
 ("サンデッキ跨線橋上","相模原市南区相模大野 サンデッキ",2495),
]

records = []

def add(pref, city, name, hint, date, year, weekday, trange, hours, ped, src, old=False, covid=False, bic=None, note=""):
    records.append({"pref":pref,"city":city,"point_name":name,"location_hint":hint,
        "survey_date":date,"year":year,"weekday":weekday,"time_range":trange,"hours":hours,
        "pedestrians":int(ped),"bicycles":(int(bic) if bic is not None else None),
        "per_hour":int(round(ped/hours)),"old":bool(old),"covid":bool(covid),
        "source_url":src,"note":note})

for name, hint, ped in HACHIOJI:
    add("東京都","八王子市",name,hint,"2023-11-28（平日）",2023,"平日","09:00-22:00",13,ped,SRC_HACHIOJI,
        note="令和5年度中心市街地歩行量調査・13時間・歩行者のみ")
for name, hint, ped in ODAWARA:
    add("神奈川県","小田原市",name,hint,"2025-12-13（土）",2025,"休日(土)","12:00-18:00",6,ped,SRC_ODAWARA,
        note="第81回主要商店街流動客調査・6時間・流動客(歩行者)")
for name, hint, ped in SAGAMI:
    add("神奈川県","相模原市",name,hint,"2022-10-23（日）",2022,"休日(日)","10:00-20:00",10,ped,SRC_SAGAMI,
        note="令和4年度商業実態調査・10時間・歩行者(中学生以上)")

# ---- 町田市 2018年度 中心市街地通行量調査（日・11-19時=8h・歩行者+自転車合計）Excel直接パース ----
def parse_machida():
    fp = TMP / "machida2018.xls"
    if not fp.exists(): print("[machida] xls無し・スキップ"); return
    df = pd.read_excel(fp, header=None)
    tot = df.shape[1]-1  # 最終列=合計
    cur=None; curname=None; n=0
    for i in range(12, df.shape[0]):
        no=df.iloc[i,2]; name=df.iloc[i,3]; dirc=str(df.iloc[i,5]).strip()
        if pd.notna(no):
            try: cur=int(no)
            except: cur=None
            curname=str(name).strip() if pd.notna(name) else None
        if dirc=="計" and cur is not None and curname:
            val=df.iloc[i,tot]
            if pd.isna(val): continue
            val=int(round(float(val)))
            if val>200000: continue  # 全地点合計行を除外
            hint=f"町田市原町田 {curname}"
            add("東京都","町田市",curname,hint,"2018-11-25（日）",2018,"休日(日)","11:00-19:00",8,val,SRC_MACHIDA,
                note="2018年度中心市街地通行量調査・8時間・歩行者+自転車合計(分離不可)")
            n+=1
    print(f"[machida] {n}地点")

# ---- 厚木市 令和6年度(2024) 中心市街地通行量調査（休日・8-20時=12h・全方向合計）Excel直接パース ----
def parse_atsugi():
    fp = TMP / "atsugi.xlsx"
    if not fp.exists(): print("[atsugi] xlsx無し・スキップ"); return
    # 各シート=1地点。総合計(休日)は既知値と一致する最大の合計値。ここでは検証済み値を用いる。
    known = {"②":11422,"③":10125,"④":4348,"⑤":4213,"⑦":5759,"⑩":17270,"⑪":8339,"⑫":3362,"⑬":4998,"⑭":5846,"⑮":12193}
    xl = pd.ExcelFile(fp)
    # シート名から地点記号を拾う（丸数字）
    circ = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
    found={}
    for nm in xl.sheet_names:
        m=[c for c in nm if c in circ]
        if not m: continue
        sym=m[0]
        if sym not in known: continue
        df=xl.parse(nm, header=None)
        vals=set()
        for v in df.values.flatten():
            try: vals.add(int(round(float(v))))
            except: pass
        if known[sym] in vals:
            found[sym]=known[sym]
    n=0
    for sym,val in found.items():
        add("神奈川県","厚木市",f"中心市街地通行量調査 地点{sym}",f"厚木市 本厚木駅周辺 中心市街地",
            "2024-11（休日）",2024,"休日(日)","08:00-20:00",12,val,SRC_ATSUGI,
            note="令和6年度中心市街地通行量調査・12時間・全方向合計(地点は番号のみ)")
        n+=1
    print(f"[atsugi] {n}地点")

for name, hint, ped in KUMAGAYA:
    add("埼玉県","熊谷市",name,hint,"2012（平成24年）",2012,"休日","10:00-19:00",9,ped,SRC_KUMAGAYA,
        old=True, note="中心市街地活性化基本計画p.78・9時間・歩行者+自転車合算(分離不可)・2012年で古い")
for name, hint, ped in KAWAGOE:
    add("埼玉県","川越市",name,hint,"2014-05-25（日）",2014,"休日(日)","10:00-19:00",9,ped,SRC_KAWAGOE,
        old=True, note="中心市街地活性化基本計画p.36・9時間・歩行者+自転車合算(分離不可)・2014年で古い")
for name, hint, ped, bic in SAITAMA:
    add("埼玉県","さいたま市",name,hint,"2021（令和3年・センサス）",2021,"平日","07:00-19:00(昼間12h)",12,ped,SRC_SAITAMA,
        covid=True, bic=bic, note="令和3年度道路交通センサス歩行者系・昼間12時間・上下合計(実数)・自転車類は台数")
# 春日部市（駅前広場アクセス集計・従前値R5。街路地点ではないため較正対象外扱い）
add("埼玉県","春日部市","春日部駅 東西駅前広場 徒歩出入者(総数)","埼玉県春日部市 春日部駅",
    "2023（令和5年度）",2023,"不明","10:00-17:00",7,15434,SRC_KASUKABE,
    note="都市再生整備計画の指標(従前値R5)・7時間・東西駅前広場の徒歩出入者総数(街路地点ではない)")

parse_machida()
parse_atsugi()

# ---- ジオコーディング（国土地理院・無料）----
_cache={}
def gsi(q):
    if q in _cache: return _cache[q]
    url="https://msearch.gsi.go.jp/address-search/AddressSearch?q="+urllib.parse.quote(q)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            d=json.loads(r.read().decode("utf-8"))
        if d:
            c=d[0]["geometry"]["coordinates"]; t=d[0]["properties"]["title"]
            _cache[q]=(t,c[1],c[0]); time.sleep(0.15); return _cache[q]
    except Exception as e:
        pass
    _cache[q]=None; time.sleep(0.15); return None

ok=0; fail=0
for rec in records:
    tries=[rec["location_hint"], f'{rec["pref"]}{rec["city"]}', rec["city"]]
    res=None
    for q in tries:
        if not q: continue
        res=gsi(q)
        if res: break
    if res:
        rec["lat"]=round(res[1],6); rec["lng"]=round(res[2],6); rec["geocode_title"]=res[0]; ok+=1
    else:
        rec["lat"]=None; rec["lng"]=None; rec["geocode_title"]=None; fail+=1

# --- 精度判定＋概位置の分散配置 ---
# 同一座標に複数地点が丸まったもの＝店名がジオコーダで解決できず市街地中心に集約された「概位置」。
# それらは precision=area とし、市街地内に決定的に少し散らして重なりを解消（※概位置と明記）。
from collections import defaultdict
groups=defaultdict(list)
for i,rec in enumerate(records):
    if rec["lat"] is None: continue
    groups[(rec["lat"],rec["lng"])].append(i)
for (la,lo),idxs in groups.items():
    if len(idxs)==1:
        records[idxs[0]]["precision"]="street"; continue
    n=len(idxs)
    for k,i in enumerate(idxs):
        ang=2*math.pi*k/n
        r=35+22*((k%3))          # 35〜79m を決定的に付与
        dlat=(r*math.cos(ang))/111000.0
        dlng=(r*math.sin(ang))/(111000.0*math.cos(math.radians(la)))
        records[i]["lat"]=round(la+dlat,6); records[i]["lng"]=round(lo+dlng,6)
        records[i]["precision"]="area"
        records[i]["note"]=(records[i]["note"]+" ／座標は概位置(市街地内に分散表示)").strip("／ ")
for rec in records:
    if rec["lat"] is None: rec["precision"]="none"

meta={"note":"実測＝自治体の歩行者通行量調査（調査年・時間帯・定義がまちまち。比較用に per_hour=1時間あたり を併記）。座標は国土地理院ジオコーダで地点名/通り/エリアから推定（precision: street=通り/丁目級, area=市/駅エリア級）。",
      "generated":"2026-09-24","count":len(records),"geocoded_ok":ok,"geocoded_fail":fail,
      "sources":[SRC_HACHIOJI,SRC_MACHIDA,SRC_ODAWARA,SRC_SAGAMI,SRC_ATSUGI,SRC_KUMAGAYA,SRC_KAWAGOE,SRC_KASUKABE,SRC_SAITAMA]}
OUT.write_text(json.dumps({"meta":meta,"points":records}, ensure_ascii=False, separators=(",",":"), allow_nan=False), encoding="utf-8")
byp={}
for r in records: byp[r["pref"]]=byp.get(r["pref"],0)+1
print(f"総地点 {len(records)} / geocode OK {ok} 失敗 {fail}")
print("都県別:", byp)
print("precision:", {p:sum(1 for r in records if r['precision']==p) for p in ['street','area','none']})
print("->", OUT)
