"""愛知・山梨の令和2年 小地域 年齢・男女別人口 statsDataId を探索"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import requests

APP_ID = os.environ.get("ESTAT_APP_ID", "")
BASE = "https://api.e-stat.go.jp/rest/3.0/app/json"

for word in ["愛知", "山梨"]:
    params = {
        "appId": APP_ID, "searchKind": 2, "statsCode": "00200521",
        "surveyYears": 2020, "searchWord": word, "limit": 80,
    }
    r = requests.get(f"{BASE}/getStatsList", params=params, timeout=60)
    lst = r.json().get("GET_STATS_LIST", {}).get("DATALIST_INF", {}).get("TABLE_INF", [])
    if isinstance(lst, dict):
        lst = [lst]
    print(f"=== {word} ===")
    for t in lst:
        title = t.get("TITLE", {})
        title_txt = title.get("$", "") if isinstance(title, dict) else str(title)
        if "年齢" in title_txt and "男女" in title_txt:
            print(f"  id={t.get('@id')}  {title_txt[:70]}")
