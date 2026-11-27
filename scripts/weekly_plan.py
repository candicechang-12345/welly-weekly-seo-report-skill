"""每週數據報告工作清單：算出這週要做哪些品牌、人工項目與 GSC 截圖連結。

用法：
    python scripts/weekly_plan.py                  # 以今天為基準（報告區間＝上週一～上週日）
    python scripts/weekly_plan.py --today 2026-11-05
    python scripts/weekly_plan.py --out reminder.md
不需要任何授權，可在 GitHub Actions 直接跑，輸出內容拿去發提醒。
"""

import argparse
import calendar
import datetime as dt
import json
from urllib.parse import urlencode

import local_config

SHEET_MTD = "https://docs.google.com/spreadsheets/d/1mXeT5C-JgHzEZyVTZwWzP_MEvO5Hg8TAdTqxd3eb3lc/edit"
REPORT_FOLDER = "https://drive.google.com/drive/folders/1HQP98bAnMrr5qd2aoVfRPiLPpCnZ4QAW"
# welly.seo.team 是這台電腦 Chrome 的第幾個帳號（/u/<N>/），每台電腦不同，設定在 local_config（預設 1）；
# 用錯帳號開 GSC 會顯示「沒有存取權限」
GSC_USER = local_config.load()["gsc_user"]
GSC_HOME = f"https://search.google.com/u/{GSC_USER}/search-console"
GSC = f"{GSC_HOME}/performance/search-analytics"
METRICS = "CLICKS,IMPRESSIONS,CTR,POSITION"
NEW_SITE = ("wellyblog.tw", "https://wellyblog.tw/")   # Welly TW 新站：GSC 是網址前置字元資源，不是 sc-domain
WELLY_KEYWORDS = {
    "SEO": ("seo", "https://welly.tw/blog/what-is-seo"),
    "SEO公司": ("seo公司", "https://welly.tw/blog/how-to-choose-seo-agency"),
}


def ymd(d: dt.date) -> str:
    return d.strftime("%Y%m%d")


def md(d: dt.date) -> str:
    return f"{d.month}/{d.day}"


def resource(site):
    return NEW_SITE[1] if site == NEW_SITE[0] else f"sc-domain:{site}"


def gsc_link(site, start, end, cmp_start, cmp_end, country, query=None, page=None):
    p = {"resource_id": resource(site), "start_date": ymd(start), "end_date": ymd(end),
         "compare_start_date": ymd(cmp_start), "compare_end_date": ymd(cmp_end), "country": country}
    if query:
        p["query"] = f"!{query}"   # ! = 完全相符
    if page:
        p["page"] = f"!{page}"
    p["metrics"] = METRICS
    return f"{GSC}?{urlencode(p)}"


ARTICLE_LISTS = {
    "welly.tw": "https://docs.google.com/spreadsheets/d/1WdYv__K7nbBPl-Tr0AHedZnvK-3Ws8ljUB-VgedbYGg/edit",   # 1-Welly文章與數據列表
    "welly.hk": "https://docs.google.com/spreadsheets/d/1rLO_nUSzUz7bMA5iLl_y3oADhv5iDr8fqEcI8uLg5RM/edit",   # HK Welly 文章與數據列表
}
DOMAIN_LOGS = {
    "welly.tw": "https://docs.google.com/spreadsheets/d/1fSuJwBAtn2pIDmdJ5RKRSXsO0No4wrMHU_0BbQuOSj4/edit",
    "welly.hk": "https://docs.google.com/spreadsheets/d/1L9OO4wPX2zs8LBIegvWxZDUIMpjQoj_-4k8pRzhbaTk/edit",
    "haveababy.tw": "https://docs.google.com/spreadsheets/d/1Tm0U453AHcpi2fpyduExnjTJgxZrJrF3ofEhF5XZlhk/edit",
}


def article_list_steps(site, name):
    """交接文件：Welly 每週、Welly HK 每月要更新文章與數據列表（文章數據列表每週三 09:00 自動更新）。"""
    return [
        f"[{name}]({ARTICLE_LISTS[site]})：「核心關鍵字追蹤」G1 或排名出現 #REF! → 到「GSCdata」刪掉全形英文字的列"
        "（ＵＴＭ／UTＭ），還有就找含「'」的重複關鍵字列刪掉",
        f"[{name}]({ARTICLE_LISTS[site]})：「核心關鍵字追蹤」本期數據貼到最右邊（僅貼上值）；下方表格的上期大字排名、頁面排名貼上值",
    ]


def domain_log_step(site):
    return (f"外鏈域名數字有變動（排程跑完的回報會提醒）→ 匯出 GSC「最常連結的網站」貼到[外鏈域名紀錄]({DOMAIN_LOGS[site]})，"
            "新增的標黃底＋註解（競品、高相關高 DR），遺失的標紅底＋註解（自建、高相關）")


def manual_metric_links(site):
    """GSC 介面才有的三項（API 拿不到）＋ Ahrefs DR／UR 的直達連結與判讀方式。"""
    rid = urlencode({"resource_id": resource(site)})
    return ["（自動，排程沒跑到再手動）" + x for x in [
        f"[GSC 網站使用體驗核心指標]({GSC_HOME}/core-web-vitals?{rid})："
        "行動裝置、桌面都是 0 個不良、0 個需要改善 → 填「良好」；沒有資料 → 「資料不足」",
        f"[GSC 連結]({GSC_HOME}/links?{rid})：外部連結的「連結總數」→ GSC外鏈數量",
        f"[最常連結的網站（更多）]({GSC_HOME}/links/drilldown?{rid}&type=DOMAIN&target=&domain=)："
        "頁面底部「共 N 列」→ GSC外鏈域名（數字有變才更新外鏈域名紀錄）",
        f"[Ahrefs {site}](https://app.ahrefs.com/v2-site-explorer/overview?mode=subdomains&target={site})：DR、首頁 UR"
        "（自動化抓到的話可略過）",
    ]]


def month_range(year, month):
    return dt.date(year, month, 1), dt.date(year, month, calendar.monthrange(year, month)[1])


def plan(today: dt.date) -> dict:
    mon = today - dt.timedelta(days=today.weekday() + 7)
    sun = mon + dt.timedelta(days=6)
    pmon, psun = mon - dt.timedelta(days=7), sun - dt.timedelta(days=7)
    # 月累：本月 1 號～分析週週日 vs 上月 1 號～上月同一天
    mtd_start = sun.replace(day=1)
    prev_end_of_month = mtd_start - dt.timedelta(days=1)
    pmtd = (prev_end_of_month.replace(day=1), prev_end_of_month.replace(day=min(sun.day, prev_end_of_month.day)))
    # 月報：報告週包含某月最後一天 → 這週做那個月（8/31–9/6 做 8 月；9/21–9/27 不做）
    monthly = None
    d = mon
    while d <= sun:
        if d.day == calendar.monthrange(d.year, d.month)[1]:
            monthly = (d.year, d.month)
        d += dt.timedelta(days=1)

    p = {"today": today, "week": (mon, sun), "prev_week": (pmon, psun), "mtd": (mtd_start, sun), "pmtd": pmtd,
         "monthly": monthly, "brands": []}

    welly = {
        "key": "Welly",
        "name": "Welly TW（每週）",
        "screenshots": [("整站（台灣，本週 vs 上週）", gsc_link("welly.tw", mon, sun, pmon, psun, "twn"))]
        + [(f"大字「{k}」查詢＋頁", gsc_link("welly.tw", mon, sun, pmon, psun, "twn", q, u))
           for k, (q, u) in WELLY_KEYWORDS.items()],
        "manual": [
            "無痕搜尋「SEO」「SEO公司」：記頁數、SEO公司 是否出現在 AIO",
            *manual_metric_links("welly.tw"),
            domain_log_step("welly.tw"),
            f"（自動，排程沒跑到再手動）[1-Welly文章與數據列表]({ARTICLE_LISTS['welly.tw']})：排程會更新下方表格、插入新欄並貼上本期的值；"
            "回報列出 #REF! 的問題列時，到「GSCdata」刪掉那幾列，再跟 Claude 說「補跑文章與數據列表」",
            "檢查完成後貼到 Slack #seo內部案專用頻道（不需要主管審核）",
        ],
    }
    p["brands"].append(welly)
    p["brands"].append({
        "key": "WellyNew",
        "name": "Welly TW 新站 wellyblog.tw（每週，報告文件【Welly】段落的「Welly新站」表格）",
        "screenshots": [("新站整站（台灣，本週 vs 上週）", gsc_link(NEW_SITE[0], mon, sun, pmon, psun, "twn"))],
        "manual": [*manual_metric_links(NEW_SITE[0]),
                   "報告文件【Welly】段落的【新站】句子由排程寫好，檢查即可"],
    })

    if monthly:
        y, m = monthly
        ms, me = month_range(y, m)
        py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
        pms, pme = month_range(py, pm)
        p["brands"].append({
            "key": "WellyHK",
            "name": f"Welly HK（{m} 月月報）",
            "screenshots": [("整站（香港，本月 vs 上月）", gsc_link("welly.hk", ms, me, pms, pme, "hkg"))],
            "manual": [*manual_metric_links("welly.hk"), domain_log_step("welly.hk"),
                       f"（自動，排程沒跑到再手動）[HK Welly 文章與數據列表]({ARTICLE_LISTS['welly.hk']})：月報週排程會更新下方表格、插入新欄並貼上本期的值；"
                       "回報列出 #REF! 的問題列時，到「GSCdata」刪掉那幾列，再跟 Claude 說「補跑文章與數據列表」"],
        })
        p["brands"].append({
            "key": "Haveababy",
            "name": f"Haveababy（{m} 月月報＋優化建議）",
            "screenshots": [("整站（台灣，本月 vs 上月）", gsc_link("haveababy.tw", ms, me, pms, pme, "twn"))],
            "manual": [*manual_metric_links("haveababy.tw"), domain_log_step("haveababy.tw"),
                       "Haveababy 分析草稿已寫入，請檢查數據、依據與結論後再發到 Slack（排程寫在本週報告文件的【HaveABaby】段落，"
                       "連結見排程跑完的回報；灰字「判讀依據」和第一行草稿說明發到 Slack 前刪掉；SERP 標【待確認】的請用無痕補上）",
                       "貼到 Slack #haveababy文章討論區 並 tag 佳軒"],
        })
    return p


def to_markdown(p: dict) -> str:
    (mon, sun), (pmon, psun) = p["week"], p["prev_week"]
    lines = [f"# 數據週報待辦｜{md(mon)}–{md(sun)}",
             "",
             f"- 報告區間：{mon}～{sun}（比較上週 {pmon}～{psun}）",
             f"- 本週品牌：{'、'.join(b['name'] for b in p['brands'])}",
             f"- 報告文件：電腦上的 Claude 排程（週四 09:00，沒開電腦就下次開 Claude 時補跑）會複製上週文件、改成 {mon:%Y/%m/%d}- {sun:%Y/%m/%d} 並改好我們品牌的標題日期（[報告資料夾]({REPORT_FOLDER})）",
             "- 同一個排程會把 GA4 四格、月累、GSC 數字、網站使用體驗核心指標、外鏈數量與域名、DR／UR 整理成彩色表格，直接插進報告文件各品牌段落（取代原本的試算表截圖，不再寫「全品項數據週報」），完成後記在雲端硬碟的「週報執行紀錄」，並在 Claude 裡列出回報。以下打勾項目是需要你做的，標「自動」的看回報確認即可。",
             ""]
    for b in p["brands"]:
        lines += [f"## {b['name']}", "", "**GSC 截圖（點連結就會套好篩選；只截彩色指標卡片）**"]
        lines += [f"- [ ] [{t}]({u})" for t, u in b["screenshots"]]
        lines += ["", "**其他人工項目**"]
        lines += [f"- [ ] {s}" for s in b["manual"]]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", help="YYYY-MM-DD，預設今天")
    ap.add_argument("--out", help="輸出 Markdown 檔")
    ap.add_argument("--cards", action="store_true", help="只輸出各品牌整站 GSC 卡片截圖網址（JSON，排程截圖用）")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    if a.cards:
        print(json.dumps({b["key"]: b["screenshots"][0][1] for b in plan(today)["brands"]}, ensure_ascii=False, indent=2))
        return
    text = to_markdown(plan(today))
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()
