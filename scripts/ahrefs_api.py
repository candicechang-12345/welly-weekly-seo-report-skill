"""Ahrefs API v3（API key）：DR／首頁 UR、SERP 前幾名。取代原本的 Ahrefs MCP 連接器。

憑證：環境變數 AHREFS_API_KEY，或 %USERPROFILE%\\.welly-seo\\ahrefs.env（一行 AHREFS_API_KEY=…，不放進專案）。
額度是全公司共用；DR＋UR 每站約 100 單位，SERP 每字依回傳列數計。

用法（工作目錄 scripts）：
  python ahrefs_api.py dr-ur --date 2026-11-16 welly.tw wellyblog.tw
  python ahrefs_api.py serp --country tw 避孕環 巴氏腺囊腫
輸出 JSON；拿不到的欄位是 null，並在 error 寫原因（例如額度不足），排程照舊改用 Chrome。
"""

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import requests

API = "https://api.ahrefs.com/v3"
ENV_FILE = Path(os.environ.get("WELLY_SEO_CRED_DIR", Path.home() / ".welly-seo")) / "ahrefs.env"


def api_key() -> str:
    key = os.environ.get("AHREFS_API_KEY")
    if not key and ENV_FILE.exists():
        env = dict(l.strip().split("=", 1) for l in ENV_FILE.read_text(encoding="utf-8").splitlines() if "=" in l)
        key = env.get("AHREFS_API_KEY")
    if not key:
        sys.exit(f"找不到 Ahrefs API key：請設定環境變數 AHREFS_API_KEY，或在 {ENV_FILE} 放一行 AHREFS_API_KEY=…")
    return key


def get(path: str, params: dict) -> dict:
    r = requests.get(f"{API}/{path}", params=params, timeout=60,
                     headers={"Authorization": f"Bearer {api_key()}", "Accept": "application/json"})
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}：{r.text[:200]}")
    return r.json()


def dr_ur(site: str, date: str) -> dict:
    out = {"site": site, "date": date, "dr": None, "ur": None}
    try:
        out["dr"] = get("site-explorer/domain-rating", {"target": site, "date": date})["domain_rating"]["domain_rating"]
        # UR 歷史是月資料點，往前抓 40 天取最後一筆
        start = (dt.date.fromisoformat(date) - dt.timedelta(days=40)).isoformat()
        hist = get("site-explorer/url-rating-history",
                   {"target": f"https://{site}/", "date_from": start, "date_to": date})["url_ratings"]
        if hist:
            out["ur"] = hist[-1]["url_rating"]
    except Exception as e:
        out["error"] = str(e)
    return out


def serp(keyword: str, country: str, top: int) -> dict:
    out = {"keyword": keyword, "country": country, "results": None}
    try:
        rows = get("serp-overview/serp-overview",
                   {"keyword": keyword, "country": country, "top_positions": top,
                    "select": "position,url,title,type"})["positions"]
        out["results"] = [r for r in rows if "organic" in (r.get("type") or [])]
        out["aio"] = any("ai_overview" in str(r.get("type")) for r in rows)
    except Exception as e:
        out["error"] = str(e)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("dr-ur", help="網域 DR 與首頁 UR")
    a.add_argument("--date", required=True, help="報告區間最後一天 YYYY-MM-DD")
    a.add_argument("sites", nargs="+")
    s = sub.add_parser("serp", help="關鍵字 SERP 自然結果")
    s.add_argument("--country", default="tw")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("keywords", nargs="+")
    args = p.parse_args()

    if args.cmd == "dr-ur":
        data = [dr_ur(site, args.date) for site in args.sites]
    else:
        data = [serp(k, args.country, args.top) for k in args.keywords]
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
