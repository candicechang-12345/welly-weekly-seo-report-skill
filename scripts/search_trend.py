"""搜尋熱度驗證（DataForSEO）：判讀「搜尋熱度降低／提升」或「點閱率大跌」時，用實際搜尋熱度確認。

- Google Trends（keywords_data/google_trends/explore/live，time_range=past_12_months）：台灣每週熱度，比較本月 vs 上月各週平均。
  2026-11-05 實測：指定日期區間拿到的每日值只有最近 10 天有數字，前面全是空值，所以改用 12 個月的每週資料；
  空值（Google 沒給）當缺資料，不當 0。
  Google Trends 是抽樣資料：同一個字隔幾分鐘再查，月平均可能差 10 個百分點以上（乳腺炎 −19% → −32%），小字更明顯，只能當輔助，以 GSC 曝光為準。每個字單獨查（Trends 是相對值，同一次請求裡的字會互相影響），一個字約 US$0.011。
- Google Ads 月搜尋量（keywords_data/google_ads/search_volume/live）：只有到上上個月左右（11/5 查只到 9 月），用來看去年同月與季節性。
  一次請求最多 1000 字，約 US$0.09。

憑證：環境變數 DATAFORSEO_LOGIN／DATAFORSEO_PASSWORD，或 %USERPROFILE%\\.welly-seo\\dataforseo.env（同樣兩行，不放進專案）。

用法（工作目錄 scripts）：
  python search_trend.py --month 2026-10 避孕環 巴氏腺囊腫
"""

import argparse
import calendar
import datetime as dt
import json
import os
import sys
from pathlib import Path

import requests

API = "https://api.dataforseo.com/v3/keywords_data"
TW = 2158
ENV_FILE = Path(os.environ.get("WELLY_SEO_CRED_DIR", Path.home() / ".welly-seo")) / "dataforseo.env"
HEAT_SAME = 0.10   # 熱度變動 ±10% 內視為持平


def auth():
    login, pw = os.environ.get("DATAFORSEO_LOGIN"), os.environ.get("DATAFORSEO_PASSWORD")
    if not (login and pw) and ENV_FILE.exists():
        env = dict(l.strip().split("=", 1) for l in ENV_FILE.read_text(encoding="utf-8").splitlines() if "=" in l)
        login, pw = env.get("DATAFORSEO_LOGIN"), env.get("DATAFORSEO_PASSWORD")
    if not (login and pw):
        raise RuntimeError(f"找不到 DataForSEO 帳密（環境變數或 {ENV_FILE}）")
    return login, pw


def _post(path, task):
    r = requests.post(f"{API}/{path}", auth=auth(), json=[task], timeout=120)
    r.raise_for_status()
    t = r.json()["tasks"][0]
    if t["status_code"] != 20000:
        raise RuntimeError(f"DataForSEO {path}：{t['status_code']} {t['status_message']}")
    return t.get("result") or []


def month_range(y, m):
    return dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1])


def trends_weekly(keyword):
    """{週起始日: 熱度或 None}；None＝Google 沒給數字（搜尋量太小或缺資料）。"""
    res = _post("google_trends/explore/live", {"keywords": [keyword], "location_code": TW, "time_range": "past_12_months"})
    for it in (res[0].get("items") or []) if res else []:
        if it.get("type") == "google_trends_graph":
            return {d["date_from"]: d["values"][0] for d in it.get("data") or []}   # 搜尋量太小時整個 data 是空的
    return {}


def ads_monthly(keywords):
    res = _post("google_ads/search_volume/live", {"keywords": list(keywords), "location_code": TW,
                                                  "language_name": "Chinese (Traditional)"})
    return {it["keyword"]: {f"{m['year']}-{m['month']:02d}": m["search_volume"] for m in (it.get("monthly_searches") or [])}
            for it in res}


def heat_word(change):
    if change is None:
        return "資料不足"
    return "持平" if abs(change) < HEAT_SAME else ("上升" if change > 0 else "下降")


def summarize(keywords, month):
    """回傳 {字: {trend: {months: {YYYY-MM: 平均}, change, word}, ads: {YYYY-MM: 月搜尋量}}}；上上月、上月、本月三個月的 Trends 平均。"""
    y, m = map(int, month.split("-"))
    months = []
    for k in (2, 1, 0):
        yy, mm = (y, m - k) if m - k > 0 else (y - 1, m - k + 12)
        months.append((yy, mm))
    out = {}
    try:
        ads = ads_monthly(keywords)
    except Exception as e:   # Ads 失敗不影響 Trends
        ads = {}
        print(f"⚠ Google Ads 搜尋量抓取失敗：{e}", file=sys.stderr)
    for kw in dict.fromkeys(keywords):
        weekly = trends_weekly(kw)
        avg, missing = {}, 0
        for yy, mm in months:
            s, e = month_range(yy, mm)
            wk = [v for d, v in weekly.items() if s <= dt.date.fromisoformat(d) <= e]   # 週起始日落在該月的週
            vals = [v for v in wk if v is not None]
            missing += len(wk) - len(vals)
            avg[f"{yy}-{mm:02d}"] = round(sum(vals) / len(vals), 1) if vals else None
        prev, cur = avg[f"{months[1][0]}-{months[1][1]:02d}"], avg[f"{months[2][0]}-{months[2][1]:02d}"]
        change = round(cur / prev - 1, 3) if prev and cur is not None else None
        out[kw] = {"trend": {"months": avg, "change": change, "word": heat_word(change),
                             "missing_weeks": missing},
                   "ads": ads.get(kw, {})}
    return out


def note(t, month):
    """灰字用的一句話：Google Trends 本月 vs 上月，加上 Ads 去年同月（季節性參考）。"""
    if not t:
        return ""
    tr = t["trend"]
    ms = list(tr["months"])
    vals = "、".join(f"{int(k[5:])} 月 {v if v is not None else '無'}" for k, v in tr["months"].items())
    txt = f"搜尋熱度（DataForSEO Google Trends 台灣，近 12 個月每週相對值的月平均）{vals}，本月 vs 上月{heat_word(tr['change'])}"
    if tr["change"] is not None:
        txt += f"（{tr['change']:+.0%}）"
    if tr["missing_weeks"] >= 3:
        txt += f"，有 {tr['missing_weeks']} 週 Google 沒給數字，字的搜尋量小，參考就好"
    ads = t.get("ads") or {}
    y, m = map(int, month.split("-"))
    ly = ads.get(f"{y - 1}-{m:02d}")
    if ly is not None:
        recent = sorted(ads)[-1]
        txt += f"；Google Ads 月搜尋量 去年 {m} 月 {ly:,}、最新 {int(recent[5:])} 月 {ads[recent]:,}"
    return txt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True)
    ap.add_argument("keywords", nargs="+")
    a = ap.parse_args()
    res = summarize(a.keywords, a.month)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    for k, v in res.items():
        print(f"{k}：{note(v, a.month)}")


if __name__ == "__main__":
    main()
