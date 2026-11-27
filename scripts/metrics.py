"""各品牌週報／月報數字的 API 算法（原 fill_weekly_block.py，2026-11-18 起不再寫試算表，由 doc_data_table.py 使用）。

GA4 四格照舊試算表品牌分頁的算法、GSC 照 SOP 國家篩選、月累＝GA4 逐日工作階段加總（口徑同舊「4.1-月累NP比較流量」）。
BRANDS 裡的試算表位置只用來讀上期人工項目（文件裡還沒有表格時）。
"""

import calendar
import datetime as dt
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession

from welly_auth import load_credentials

ROWS = ["總工作階段", "自然流量工作階段", "自然流量平均參與時間", "自然流量跳出率", "點擊量", "曝光量",
        "平均點閱率", "平均排序", "良好網站比例", "DR", "UR", "GSC外鏈域名", "GSC外鏈數量", "本月累積非付費流量"]
MANUAL = ["良好網站比例", "DR", "UR", "GSC外鏈域名", "GSC外鏈數量"]
NATURAL_MEDIUMS = ["organic", "(none)", "referral", "(not set)"]

# 各品牌在「數據週報」分頁的位置。first_row＝「總工作階段」那列；skip_after_natural＝
# 「自然流量工作階段」下面多一列（Welly、Haveababy 有一列舊公式要跳過）。GSC 國家已用同事填的值驗證。
BRANDS = {
    "Welly": {"period": "week", "site": "sc-domain:welly.tw", "country": "twn", "ga4": "309886039",
              "label_row": 60, "this_col": "C", "prev_col": "D", "first_row": 62, "skip_after_natural": True},
    "WellyHK": {"period": "month", "site": "sc-domain:welly.hk", "country": "hkg", "ga4": "374529723",
                "label_row": 96, "this_col": "C", "prev_col": "D", "first_row": 98, "skip_after_natural": False},
    "Haveababy": {"period": "month", "site": "sc-domain:haveababy.tw", "country": "twn", "ga4": "310316232",
                  "label_row": 2, "this_col": "I", "prev_col": "J", "first_row": 4, "skip_after_natural": True},   # 4.1 表裡叫「婦產科」
    # Welly TW 新站（2026-11-17 在「數據週報」B130:F146 新增區塊，格式複製 WellyHK）；GSC 是網址前置字元資源
    "WellyNew": {"period": "week", "site": "https://wellyblog.tw/", "country": "twn", "ga4": "562289258",
                 "label_row": 131, "this_col": "C", "prev_col": "D", "first_row": 133, "skip_after_natural": False,
                 "sparse": True},   # 新站流量小，整天 0 工作階段是正常的，不當成 GA4 缺資料
    "早安毛": {"period": "week", "site": "sc-domain:daypets.tw", "country": None, "ga4": "532871090",
              "label_row": 114, "this_col": "I", "prev_col": "J", "first_row": 116, "skip_after_natural": False},
}


def row_numbers(cfg):
    rows, r = {}, cfg["first_row"]
    for name in ROWS:
        rows[name] = r
        r += 2 if (name == "自然流量工作階段" and cfg["skip_after_natural"]) else 1
    return rows


def gsc_totals(site, country, start, end):
    s = AuthorizedSession(load_credentials(allow_browser=False))
    body = {"startDate": start, "endDate": end}
    if country:
        body["dimensionFilterGroups"] = [{"filters": [{"dimension": "country", "operator": "equals", "expression": country}]}]
    r = s.post(f"https://www.googleapis.com/webmasters/v3/sites/{quote(site, safe='')}/searchAnalytics/query", json=body)
    r.raise_for_status()
    rows = r.json().get("rows")
    if not rows or not rows[0]["impressions"]:
        return {"點擊量": 0, "曝光量": 0, "平均點閱率": "", "平均排序": ""}
    row = rows[0]
    return {"點擊量": round(row["clicks"]), "曝光量": round(row["impressions"]),
            "平均點閱率": round(row["ctr"], 3), "平均排序": round(row["position"], 1)}


def ga4_sheet_method(prop, start, end):
    """照 Sheet 品牌分頁的算法重現 GA4 四格：總工作階段＝全部來源加總；自然流量＝SOP 4 種來源；
    平均參與時間、跳出率＝這 4 種來源各自數值的直接平均（不加權），時間轉成 mm:ss 文字。"""
    s = AuthorizedSession(load_credentials(allow_browser=False))
    r = s.post(f"https://analyticsdata.googleapis.com/v1beta/properties/{prop}:runReport", json={
        "dateRanges": [{"startDate": start, "endDate": end}], "dimensions": [{"name": "sessionMedium"}],
        "metrics": [{"name": "sessions"}, {"name": "averageSessionDuration"}, {"name": "bounceRate"}], "limit": 1000})
    r.raise_for_status()
    rows = {x["dimensionValues"][0]["value"]: [float(m["value"]) for m in x["metricValues"]] for x in r.json().get("rows", [])}
    if not rows:   # 新站剛上線的週可能整週沒有工作階段
        print(f"WARNING GA4 {prop} {start}～{end} 沒有任何工作階段")
        return {"總工作階段": 0, "自然流量工作階段": 0, "自然流量平均參與時間": "", "自然流量跳出率": ""}
    nat = [rows[m] for m in NATURAL_MEDIUMS if m in rows]
    if not nat:
        return {"總工作階段": int(sum(v[0] for v in rows.values())), "自然流量工作階段": 0,
                "自然流量平均參與時間": "", "自然流量跳出率": ""}
    secs = round(sum(v[1] for v in nat) / len(nat))
    return {"總工作階段": int(sum(v[0] for v in rows.values())), "自然流量工作階段": int(sum(v[0] for v in nat)),
            "自然流量平均參與時間": f"{secs // 60:02d}:{secs % 60:02d}",
            "自然流量跳出率": sum(v[2] for v in nat) / len(nat)}


def ga4_daily_sum(prop, start, end):
    """月累＝逐日全部工作階段加總（舊 4.1 表 SyncWith「Date × Sessions」的口徑，名稱寫非付費但沒排除付費）。
    回傳 (加總, 缺資料的日期)；GA4 偶爾整天資料消失，有缺就要提醒重跑。"""
    s = AuthorizedSession(load_credentials(allow_browser=False))
    r = s.post(f"https://analyticsdata.googleapis.com/v1beta/properties/{prop}:runReport", json={
        "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
        "dimensions": [{"name": "date"}], "metrics": [{"name": "sessions"}], "limit": 400})
    r.raise_for_status()
    days = {x["dimensionValues"][0]["value"]: int(x["metricValues"][0]["value"]) for x in r.json().get("rows", [])}
    expected = {(start + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((end - start).days + 1)}
    return sum(days.values()), sorted(expected - days.keys())


def mtd_ranges(cfg, cur):
    """週報：本月 1 號～本週週日 vs 上月 1 號～上月同一天；月報：本月整月 vs 上月整月。"""
    cs, ce = cur
    if cfg["period"] == "month":
        pe = cs - dt.timedelta(days=1)
        return (cs, ce), (pe.replace(day=1), pe)
    ms = ce.replace(day=1)
    pme = ms - dt.timedelta(days=1)
    return (ms, ce), (pme.replace(day=1), pme.replace(day=min(ce.day, pme.day)))


def periods(cfg, week, month):
    if cfg["period"] == "week":
        mon = dt.date.fromisoformat(week)
        return (mon, mon + dt.timedelta(days=6)), (mon - dt.timedelta(days=7), mon - dt.timedelta(days=1))
    y, m = map(int, month.split("-"))
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    rng = lambda yy, mm: (dt.date(yy, mm, 1), dt.date(yy, mm, calendar.monthrange(yy, mm)[1]))
    return rng(y, m), rng(py, pm)


def label(start, end):
    return f"{start.month}/{start.day}-{end.month}/{end.day}"
