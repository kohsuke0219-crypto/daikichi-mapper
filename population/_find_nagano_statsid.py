import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import requests
app=os.environ.get("ESTAT_APP_ID","")
r=requests.get("https://api.e-stat.go.jp/rest/3.0/app/json/getStatsList",
    params={"appId":app,"searchKind":2,"statsCode":"00200521","surveyYears":2020,"searchWord":"長野","limit":80},timeout=60)
lst=r.json().get("GET_STATS_LIST",{}).get("DATALIST_INF",{}).get("TABLE_INF",[])
if isinstance(lst,dict): lst=[lst]
for t in lst:
    ti=t.get("TITLE",{}); tt=ti.get("$","") if isinstance(ti,dict) else str(ti)
    if "年齢" in tt and "男女" in tt:
        print("estat id=", t.get("@id"), tt[:50])
