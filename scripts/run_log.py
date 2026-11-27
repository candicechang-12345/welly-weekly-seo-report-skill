"""用雲端硬碟的「週報執行紀錄」試算表判斷「這週的自動填表是不是已經在某台電腦跑過」，並留下回報。
取代 issue_lock.py（GitHub Issue），同事不需要 GitHub 帳號。

  python scripts/run_log.py check   # 結束碼 0＝可以跑；2＝別台已跑完或正在跑（印出是誰）
  python scripts/run_log.py start   # 記一列「填表中」（電腦名稱、負責人、時間）
  python scripts/run_log.py done --body-file report.md [--doc <報告文件連結>]   # 改成「已完成」＋回報
  python scripts/run_log.py fail --body-file report.md                        # 改成「未完成」，下次可重跑
可加 --today YYYY-MM-DD 指定基準日。
「填表中」超過 3 小時視為上次中斷，check 會允許重跑。

試算表由本程式在交接資料夾建立（drive.file 只能改自己建立的檔案，所以不能手動先開一份）。
欄位：週次｜狀態｜電腦｜負責人｜開始｜結束｜報告文件｜回報
"""

import argparse
import datetime as dt
import socket
import sys

from google.auth.transport.requests import AuthorizedSession

import local_config
from weekly_plan import plan
from welly_auth import LOCAL_SCOPES, load_credentials

NAME = "週報執行紀錄"
HEADER = ["週次", "狀態", "電腦", "負責人", "開始", "結束", "報告文件", "回報"]
RUNNING, DONE, FAILED = "填表中", "已完成", "未完成"
STALE_HOURS = 3
DRIVE = "https://www.googleapis.com/drive/v3/files"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
FMT = "%Y-%m-%d %H:%M"


def week_title(today):
    mon, sun = plan(today)["week"]
    return f"{mon:%Y/%m/%d}–{sun:%m/%d}"   # 帶年份，跨年不會撞到同一列


class Log:
    def __init__(self):
        self.s = AuthorizedSession(load_credentials(allow_browser=False, scopes=LOCAL_SCOPES))
        self.folder = local_config.load()["handover_folder"]
        self.sid = self._find()

    def _find(self):
        r = self.s.get(DRIVE, params={
            "q": f"'{self.folder}' in parents and name='{NAME}' and trashed=false "
                 "and mimeType='application/vnd.google-apps.spreadsheet'",
            "fields": "files(id)", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"})
        r.raise_for_status()
        files = r.json()["files"]
        return files[0]["id"] if files else None

    def _create(self):
        r = self.s.post(DRIVE, params={"supportsAllDrives": "true", "fields": "id"},
                        json={"name": NAME, "parents": [self.folder],
                              "mimeType": "application/vnd.google-apps.spreadsheet"})
        r.raise_for_status()
        self.sid = r.json()["id"]
        self._put("A1:H1", [HEADER])
        print(f"已建立「{NAME}」：https://docs.google.com/spreadsheets/d/{self.sid}/edit")

    def _put(self, rng, values):
        r = self.s.put(f"{SHEETS}/{self.sid}/values/{rng}", params={"valueInputOption": "RAW"},
                       json={"values": values})
        r.raise_for_status()

    def rows(self):
        if not self.sid:
            return []
        r = self.s.get(f"{SHEETS}/{self.sid}/values/A2:H")
        r.raise_for_status()
        return [row + [""] * (len(HEADER) - len(row)) for row in r.json().get("values", [])]

    def find_row(self, title):
        """回傳 (試算表列號, 內容)；沒有就 (None, None)。"""
        for i, row in enumerate(self.rows(), start=2):
            if row[0] == title:
                return i, row
        return None, None

    def write(self, title, row_no, row):
        if not self.sid:
            self._create()
        if row_no is None:
            row_no = len(self.rows()) + 2
        self._put(f"A{row_no}:H{row_no}", [row])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["check", "start", "done", "fail"])
    ap.add_argument("--today")
    ap.add_argument("--body-file")
    ap.add_argument("--doc", default="", help="本週報告文件連結")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    title, host, who = week_title(today), socket.gethostname(), local_config.load()["operator"]
    now = dt.datetime.now()
    log = Log()
    row_no, row = log.find_row(title)

    if a.action == "check":
        if row and row[1] == DONE:
            print(f"本週已完成：{title}（{row[3]}｜{row[2]}｜{row[5]}），本機略過")
            sys.exit(2)
        if row and row[1] == RUNNING:
            try:
                fresh = now - dt.datetime.strptime(row[4], FMT) < dt.timedelta(hours=STALE_HOURS)
            except ValueError:
                fresh = False
            if fresh:
                print(f"別台電腦正在填表：{title}（{row[3]}｜{row[2]}｜{row[4]} 開始），本機略過")
                sys.exit(2)
            print("「填表中」已超過 3 小時，視為上次中斷，可以重跑")
        print(f"可以執行：{title}")
        return

    if a.action == "start":
        log.write(title, row_no, [title, RUNNING, host, who, now.strftime(FMT), "", "", ""])
        print(f"已登記：{title}｜{who}｜{host}")
        return

    if not row:
        sys.exit("執行紀錄裡找不到本週，請先執行 start")
    body = open(a.body_file, encoding="utf-8").read() if a.body_file else ""
    row[1] = DONE if a.action == "done" else FAILED
    row[2], row[3], row[5] = host, who, now.strftime(FMT)
    row[6] = a.doc or row[6]
    row[7] = body[:49000]   # 單一儲存格上限 50,000 字
    log.write(title, row_no, row)
    print(f"已更新執行紀錄：{title} → {row[1]}（https://docs.google.com/spreadsheets/d/{log.sid}/edit）")


if __name__ == "__main__":
    main()
