"""複製上週的「內部專案數據」報告文件，改檔名，並把我們負責品牌的標題日期改成本期。

  - 上週文件：報告資料夾裡，檔名「YYYY/MM/DD- YYYY/MM/DD 內部專案數據」日期最新的那份
  - 新檔名：本週區間；已經存在就跳過（可以重複執行）
  - 改標題：【Welly】每週改；【Welly HK】【HaveABaby】只在月報週改成該月。律所段落不動。
權限：drive.readonly 讀上週文件，drive.file 只能改本程式建立的新文件。

用法：python scripts/copy_weekly_doc.py [--today YYYY-MM-DD] [--dry-run]
"""

import argparse
import datetime as dt
import re

from google.auth.transport.requests import AuthorizedSession

from weekly_plan import plan
from welly_auth import LOCAL_SCOPES, load_credentials

FOLDER = "1HQP98bAnMrr5qd2aoVfRPiLPpCnZ4QAW"   # 內部專案每週數據分析
TITLE_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})- (\d{4})/(\d{2})/(\d{2}) 內部專案數據$")
DRIVE = "https://www.googleapis.com/drive/v3/files"
DOCS = "https://docs.googleapis.com/v1/documents"


def doc_title(start, end):
    return f"{start:%Y/%m/%d}- {end:%Y/%m/%d} 內部專案數據"


def list_reports(s):
    r = s.get(DRIVE, params={"q": f"'{FOLDER}' in parents and mimeType='application/vnd.google-apps.document' and trashed=false",
                             "fields": "files(id,name)", "pageSize": 200, "orderBy": "createdTime desc"})
    r.raise_for_status()
    return [f for f in r.json()["files"] if TITLE_RE.match(f["name"])]


def heading_texts(s, doc_id):
    r = s.get(f"{DOCS}/{doc_id}")
    r.raise_for_status()
    texts = []
    for el in r.json()["body"]["content"]:
        para = el.get("paragraph")
        if para:
            texts.append("".join(e.get("textRun", {}).get("content", "") for e in para["elements"]).strip())
    return texts


def replacements(texts, week, monthly_range):
    """回傳 [(舊字串, 新字串)]：只抓我們三個品牌的標題日期。"""
    (mon, sun) = week
    rules = [(r"【Welly】\s*([\d/]+\s*[~～-]\s*[\d/]+)", f"{mon.month}/{mon.day}~{sun.month}/{sun.day}")]
    if monthly_range:
        ms, me = monthly_range
        new = f"{ms.month}/{ms.day}-{me.month}/{me.day}"
        rules += [(r"【Welly HK】\s*([\d/]+\s*[~～-]\s*[\d/]+)", new), (r"【HaveABaby】\s*([\d/]+\s*[~～-]\s*[\d/]+)", new)]
    out = []
    for pattern, new in rules:
        for t in texts:
            m = re.search(pattern, t)
            if m and m.group(1) != new:
                out.append((m.group(0), m.group(0).replace(m.group(1), new)))
                break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", help="YYYY-MM-DD，預設今天")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    p = plan(today)
    mon, sun = p["week"]
    monthly_range = None
    if p["monthly"]:
        import calendar
        y, m = p["monthly"]
        monthly_range = (dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1]))

    s = AuthorizedSession(load_credentials(allow_browser=False, scopes=LOCAL_SCOPES))
    reports = list_reports(s)
    new_name = doc_title(mon, sun)
    existing = next((f for f in reports if f["name"] == new_name), None)
    if existing:
        print(f"已存在：{new_name}（{existing['id']}），不重複複製")
        return
    prev = max((f for f in reports if f["name"] < new_name), key=lambda f: f["name"], default=None)
    if not prev:
        raise SystemExit("找不到上週的報告文件")
    texts = heading_texts(s, prev["id"])
    reps = replacements(texts, (mon, sun), monthly_range)
    print(f"來源：{prev['name']} → 新檔：{new_name}")
    for old, new in reps:
        print(f"  {old}  →  {new}")
    if a.dry_run:
        return

    r = s.post(f"{DRIVE}/{prev['id']}/copy", json={"name": new_name, "parents": [FOLDER]}, params={"fields": "id,name"})
    r.raise_for_status()
    new_id = r.json()["id"]
    if reps:
        req = [{"replaceAllText": {"containsText": {"text": old, "matchCase": True}, "replaceText": new}} for old, new in reps]
        r = s.post(f"{DOCS}/{new_id}:batchUpdate", json={"requests": req})
        r.raise_for_status()
    print(f"完成：https://docs.google.com/document/d/{new_id}/edit")


if __name__ == "__main__":
    main()
