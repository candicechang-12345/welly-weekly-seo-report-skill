"""welly.seo.team 的 GSC / GA4 OAuth 授權與連線測試。

用法：
    python scripts/welly_auth.py          # 第一次：開瀏覽器登入授權，之後自動檢查連線
    python scripts/welly_auth.py --check  # 只用已存的授權檢查連線（不開瀏覽器）

憑證都放在 %USERPROFILE%\\.welly-seo\\（不在專案資料夾內）：
    client_secret.json  ← 從 GCP 下載的 OAuth 用戶端檔，改名後放這裡
    token.json          ← 本腳本授權後自動產生（含 refresh token，等同密碼）
"""

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
]
# 寫入只透過 sheets_io.py，該模組只允許寫兩份報表原檔
SHEETS_SCOPES = SCOPES + ["https://www.googleapis.com/auth/spreadsheets"]
# 複製週報文件：drive.readonly 讀上週文件、drive.file 只能改「本程式自己建立」的檔案（複製出來的新文件）
DOCS_SCOPES = ["https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/drive.file"]
LOCAL_SCOPES = SHEETS_SCOPES + DOCS_SCOPES   # 使用者電腦上的完整授權
CRED_DIR = Path(os.environ.get("WELLY_SEO_CRED_DIR", Path.home() / ".welly-seo"))
CLIENT_SECRET = CRED_DIR / "client_secret.json"
TOKEN = CRED_DIR / "token.json"
SITE_KEYWORDS = ("welly.tw", "welly.hk", "haveababy", "wellyblog")


def load_credentials(allow_browser: bool, scopes: list[str] = SCOPES) -> Credentials:
    creds = None
    if TOKEN.exists():
        granted = json.loads(TOKEN.read_text(encoding="utf-8")).get("scopes") or []
        if set(scopes) <= set(granted):
            creds = Credentials.from_authorized_user_file(str(TOKEN), granted)
        else:  # 需要的權限範圍比已授權的多 → 要重新登入
            print("需要更多權限範圍，需要重新登入授權。")
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_token(creds)
            return creds
        except Exception as e:  # refresh token 失效（撤銷、改密碼、6 個月未用、或同意畫面仍在「測試中」）
            print(f"授權已失效，需要重新登入：{e}")
    if not allow_browser:
        sys.exit("沒有可用的授權。請不加 --check 重新執行一次。")
    if not CLIENT_SECRET.exists():
        sys.exit(f"找不到 {CLIENT_SECRET}\n請把 GCP 下載的 OAuth 用戶端 JSON 改名為 client_secret.json 放到這個資料夾。")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), scopes)
    print("即將開啟瀏覽器，請登入 welly.seo.team 並按「繼續／允許」。")
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    save_token(creds)
    return creds


def save_token(creds: Credentials) -> None:
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(creds.to_json(), encoding="utf-8")


def last_week() -> tuple[str, str]:
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday() + 7)
    return monday.isoformat(), (monday + dt.timedelta(days=6)).isoformat()


def check_gsc(session: AuthorizedSession, start: str, end: str) -> None:
    print("\n== Search Console ==")
    r = session.get("https://www.googleapis.com/webmasters/v3/sites")
    r.raise_for_status()
    sites = r.json().get("siteEntry", [])
    if not sites:
        print("（這個帳號在 GSC 看不到任何資源）")
    for s in sites:
        url, level = s["siteUrl"], s["permissionLevel"]
        if not any(k in url for k in SITE_KEYWORDS):
            continue
        line = f"- {url}  權限：{level}"
        if any(k in url for k in SITE_KEYWORDS) and level != "siteUnverifiedUser":
            q = session.post(
                f"https://www.googleapis.com/webmasters/v3/sites/{quote(url, safe='')}/searchAnalytics/query",
                json={"startDate": start, "endDate": end},
            )
            if q.ok and q.json().get("rows"):
                row = q.json()["rows"][0]
                line += f"  | {start}~{end} 點擊 {row['clicks']:.0f}、曝光 {row['impressions']:.0f}、排名 {row['position']:.1f}"
            else:
                line += f"  | 查詢失敗或無資料（HTTP {q.status_code}）"
        print(line)


def check_ga4(session: AuthorizedSession, start: str, end: str) -> None:
    print("\n== GA4 ==")
    r = session.get("https://analyticsadmin.googleapis.com/v1beta/accountSummaries")
    if not r.ok:
        print(f"列出資源失敗（HTTP {r.status_code}）：請確認 GCP 已啟用 Google Analytics Admin API。")
        return
    for acc in r.json().get("accountSummaries", []):
        for p in acc.get("propertySummaries", []):
            if not any(k in p.get("displayName", "").lower() for k in SITE_KEYWORDS):
                continue
            pid = p["property"].split("/")[-1]
            line = f"- {acc.get('displayName')} / {p.get('displayName')}  資源 ID：{pid}"
            rep = session.post(
                f"https://analyticsdata.googleapis.com/v1beta/properties/{pid}:runReport",
                json={"dateRanges": [{"startDate": start, "endDate": end}], "metrics": [{"name": "sessions"}]},
            )
            if rep.ok:
                rows = rep.json().get("rows", [])
                line += f"  | {start}~{end} 工作階段 {rows[0]['metricValues'][0]['value'] if rows else 0}"
            else:
                line += f"  | 報表失敗（HTTP {rep.status_code}）"
            print(line)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只檢查連線，不開瀏覽器")
    parser.add_argument("--local", "--sheets", dest="local", action="store_true", help="使用者電腦用的完整授權：再加 Sheets 寫入與複製週報文件（Drive）")
    args = parser.parse_args()

    creds = load_credentials(allow_browser=not args.check, scopes=LOCAL_SCOPES if args.local else SCOPES)
    session = AuthorizedSession(creds)
    start, end = last_week()
    print(f"授權 OK，token 存在 {TOKEN}")
    check_gsc(session, start, end)
    check_ga4(session, start, end)


if __name__ == "__main__":
    main()
