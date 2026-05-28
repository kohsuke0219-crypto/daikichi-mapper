"""e-Stat API の統計表IDを調べるデバッグスクリプト。"""
import os
import requests

APP_ID = os.environ.get("ESTAT_APP_ID", "")
BASE = "https://api.e-stat.go.jp/rest/3.0/app/json"


def find_tables(search_word="", stats_code="", survey_date="", limit=20, offset=0):
    url = f"{BASE}/getStatsList"
    params = {"appId": APP_ID, "limit": limit}
    if stats_code:
        params["statsCode"] = stats_code
    if search_word:
        params["searchWord"] = search_word
    if survey_date:
        params["surveyYears"] = survey_date
    if offset:
        params["startPosition"] = offset + 1
    r = requests.get(url, params=params, timeout=30)
    data = r.json()
    result = data.get("GET_STATS_LIST", {})
    total = result.get("RESULT", {}).get("TOTAL_NUMBER", 0)
    tables = result.get("DATALIST_INF", {}).get("TABLE_INF", [])
    if isinstance(tables, dict):
        tables = [tables]
    print(f"総ヒット: {total}件 / 取得: {len(tables)}件")
    for t in tables:
        tid    = t.get("@id", "")
        survey = t.get("SURVEY_DATE", "")
        title  = t.get("TITLE", {})
        tname  = title.get("$", "") if isinstance(title, dict) else str(title)
        print(f"  {tid} | {survey} | {tname}")


def get_meta(stats_data_id: str):
    """指定した統計表のメタ情報（分類コード）を表示する。"""
    url = f"{BASE}/getMetaInfo"
    params = {"appId": APP_ID, "statsDataId": stats_data_id}
    r = requests.get(url, params=params, timeout=30)
    data = r.json()
    cls_inf = (
        data.get("GET_META_INFO", {})
            .get("METADATA_INF", {})
            .get("CLASS_INF", {})
            .get("CLASS_OBJ", [])
    )
    if isinstance(cls_inf, dict):
        cls_inf = [cls_inf]
    for obj in cls_inf:
        print(f"\n【{obj.get('@id')}】{obj.get('@name')}")
        classes = obj.get("CLASS", [])
        if isinstance(classes, dict):
            classes = [classes]
        for c in classes:
            print(f"  {c.get('@code')} : {c.get('@name')}")


if __name__ == "__main__":
    # cat01 の全コードを確認（area はスキップ）
    print("=== 8003006792: cat01 全コード ===")
    url = f"{BASE}/getMetaInfo"
    params = {"appId": APP_ID, "statsDataId": "8003006792"}
    r = requests.get(url, params=params, timeout=30)
    data = r.json()
    cls_inf = (
        data.get("GET_META_INFO", {})
            .get("METADATA_INF", {})
            .get("CLASS_INF", {})
            .get("CLASS_OBJ", [])
    )
    if isinstance(cls_inf, dict):
        cls_inf = [cls_inf]
    for obj in cls_inf:
        oid = obj.get('@id')
        if oid == "area":
            print(f"\n【{oid}】{obj.get('@name')} - 省略")
            continue
        print(f"\n【{oid}】{obj.get('@name')}")
        classes = obj.get("CLASS", [])
        if isinstance(classes, dict):
            classes = [classes]
        for c in classes:
            print(f"  {c.get('@code')} : {c.get('@name')}")
