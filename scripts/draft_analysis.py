"""Haveababy 月報「分析文字」草稿：抓 GSC／GA4／數據週報的數字，依原 SOP 的判讀觀念寫成草稿，寫進當週報告文件的【HaveABaby】段落。

黑字照過去報告的句型寫給客戶看（結論併在句子裡）；每點底下有灰字「數據」「判讀依據」，發到 Slack 前刪掉。
草稿只取代【HaveABaby】標題到「本月 vs 上月」截圖之間的文字；截圖區、其他品牌、律所段落都不動。

用法（工作目錄 scripts，Python 用 .venv）：
  python draft_analysis.py collect --month 2026-10             # 抓數據 → drafts/2026-10_Haveababy_analysis.json，印出要查 SERP 的字
  python draft_analysis.py outline <網址> [<網址> ...]          # 看文章的 H1／H2／H3、FAQ、schema（比對 SERP 前幾名用）
  python draft_analysis.py write --month 2026-10 --doc <文件ID> [--notes notes.json] [--dry-run]
  python draft_analysis.py test-copy --source <文件ID>          # 開發測試用：複製一份「[TEST] …」到 welly.seo.team 的我的雲端硬碟

notes.json（排程任務用 Chrome／Ahrefs 查完 SERP 後寫，沒有也能跑，缺的地方會留【待確認】）：
  {"links": {"links": 1350, "domains": 133},   ← 選填；數據週報 I 欄還沒填本月時用
   "serp_source": "Chrome 無痕，11/5",          ← 選填；寫在草稿第一行
   "serp": {"<關鍵字>": {"rank": "無痕第 3 名", "aio": true}},
   "targets": {"<文章網址>": {"intent": "原因／症狀／治療",
                              "suggestions": ["H1 標題：往…方面調整。", "新增內容：在「…」前新增 H2 段落 →「…」。", "新增 FAQ 段落，並建立 schema。"],
                              "evidence": "SERP 首頁前幾名都有…，HaveABaby 缺…（灰字，給自己看的依據）"}},
   "extra": ["其他建議（例如圖片壓縮）"]}

寫入限制：標題「[TEST]」開頭的副本；或 copy_weekly_doc.py 建立的當週報告文件（2026/10/26 那週以後，且該週是月報週）。
權限上 drive.file 本來就只能改本程式建立的檔案；段落裡已有草稿標記時不覆蓋（使用者可能改過），要重寫加 --force。
"""

import argparse
import calendar
import datetime as dt
import html
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import quote

import requests
from google.auth.transport.requests import AuthorizedSession

from copy_weekly_doc import DOCS, DRIVE, TITLE_RE
from weekly_plan import plan
from welly_auth import LOCAL_SCOPES, load_credentials

SITE = "sc-domain:haveababy.tw"
COUNTRY = "twn"
GA4 = "310316232"
NATURAL_MEDIUMS = ["organic", "(none)", "referral", "(not set)"]
WEEKLY_SHEET_TAB = "數據週報"
SHEET_CELLS = "I2:J18"          # Haveababy 區塊（metrics.py BRANDS：label 第 2 列、I 本期、J 上期），只剩舊資料可讀
SHEET_ROW = {"label": 0, "domains": 14, "links": 15}   # 相對 I2：外鏈域名第 16 列、外鏈數量第 17 列
FIRST_WEEK = dt.date(2026, 10, 26)
MARKER = "〔Claude 草稿"
OUT_DIR = Path(__file__).resolve().parent.parent / "drafts"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36"}

# 台灣連假（行政院人事行政總處行事曆）。每年 1 月補下一年；沒列到的年份會在草稿標【待確認】。
HOLIDAYS = {
    2026: [("元旦", "01-01", "01-01"), ("春節", "02-14", "02-22"), ("和平紀念日", "02-27", "03-01"),
           ("兒童節及清明節", "04-03", "04-06"), ("勞動節", "05-01", "05-03"), ("端午節", "06-19", "06-21"),
           ("中秋節及教師節", "09-25", "09-28"), ("國慶日", "10-09", "10-11"), ("光復節", "10-24", "10-26"),
           ("行憲紀念日", "12-25", "12-27")],
    # 116 年政府行政機關辦公日曆表（2026-05 核定）；端午、中秋、教師節落在週間只放當天
    2027: [("元旦", "01-01", "01-03"), ("春節", "02-04", "02-10"), ("和平紀念日", "02-27", "03-01"),
           ("兒童節及清明節", "04-03", "04-06"), ("勞動節", "04-30", "05-02"), ("端午節", "06-09", "06-09"),
           ("中秋節", "09-15", "09-15"), ("教師節", "09-28", "09-28"), ("國慶日", "10-09", "10-11"),
           ("光復節", "10-23", "10-25"), ("行憲紀念日", "12-24", "12-26"), ("元旦補假", "12-31", "12-31")],
}

# 原 SOP「四、數據分析基礎概念」4. 排名、曝光、點擊的關係
MATRIX = {
    ("up", "+", "+"): "正常",
    ("up", "+", "-"): "不合理，點擊率降低；要看點擊率是否長期偏低或低於 1%，是的話調整 meta、標題、前言",
    ("up", "-", "-"): "搜尋熱度降低",
    ("up", "-", "+"): "搜尋熱度降低，meta 可能寫得不錯",
    ("same", "+", "+"): "搜尋熱度提升",
    ("same", "+", "-"): "搜尋熱度提升，但 meta 可能不夠吸睛",
    ("same", "-", "-"): "搜尋熱度降低",
    ("same", "-", "+"): "搜尋熱度降低，meta 可能寫得不錯",
    ("down", "+", "+"): "搜尋熱度提升",
    ("down", "+", "-"): "搜尋熱度提升，且 meta 可能不夠吸睛",
    ("down", "-", "-"): "排名下降帶動曝光、點擊下降（正常連動）",
    ("down", "-", "+"): "曝光下降正常，meta 可能寫得不錯",
}
# 對照表的「該怎麼做」（SPEC「Haveababy 月報數據分析框架」三）；數字小＝越要優先處理，9＝觀察
ACTION = {
    ("up", "+", "+"): (9, "不用處理"),
    ("up", "+", "-"): (2, "點閱率長期偏低或低於 1%，就調整 meta、標題、前言"),
    ("up", "-", "-"): (9, "觀察"),
    ("up", "-", "+"): (9, "觀察"),
    ("same", "+", "+"): (9, "觀察"),
    ("same", "+", "-"): (2, "調整標題、描述"),
    ("same", "-", "-"): (9, "觀察，看是否為季節性"),
    ("same", "-", "+"): (9, "觀察"),
    ("down", "+", "+"): (9, "觀察"),
    ("down", "+", "-"): (1, "調整標題、描述，並查排名原因"),
    ("down", "-", "-"): (0, "調整內容：對照 SERP 首頁做潛力關鍵字調整、文章內容調整、外鏈建立"),
    ("down", "-", "+"): (1, "查排名原因"),
}
RANK_WORD = {"up": "排名上升", "same": "排名不變", "down": "排名下降"}
MIN_WORD_IMPR = 50   # 選字時上月曝光太少的字不看（雜訊）


# ---------- 數據 ----------

def month_range(y, m):
    return dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1])


def prev_month(y, m):
    return (y, m - 1) if m > 1 else (y - 1, 12)


class GSC:
    def __init__(self, s):
        self.s, self.url = s, f"https://www.googleapis.com/webmasters/v3/sites/{quote(SITE, safe='')}/searchAnalytics/query"

    def query(self, start, end, dims=(), filters=(), limit=25000):
        """一次最多 25,000 列，用 startRow 翻頁抓完。
        2026-11-05 修正：以前只抓第一頁，haveababy.tw 一個月「查詢＋頁」超過 25,000 列，
        沒抓到的組合被當成「本月沒有排名」，選出 story-02、infertility-16 兩個假的排名大跌。"""
        flt = [{"dimension": "country", "operator": "equals", "expression": COUNTRY}]
        flt += [{"dimension": d, "operator": "equals", "expression": v} for d, v in filters]
        rows, start_row = [], 0
        while True:
            r = self.s.post(self.url, json={"startDate": str(start), "endDate": str(end), "dimensions": list(dims),
                                            "dimensionFilterGroups": [{"filters": flt}], "rowLimit": limit,
                                            "startRow": start_row})
            r.raise_for_status()
            page = r.json().get("rows", [])
            rows += page
            if len(page) < limit:
                break
            start_row += limit
        return [{"keys": x.get("keys", []), "clicks": round(x["clicks"]), "impressions": round(x["impressions"]),
                 "ctr": x["ctr"], "position": round(x["position"], 1)} for x in rows]

    def total(self, start, end, filters=()):
        rows = self.query(start, end, filters=filters)
        return rows[0] if rows else {"keys": [], "clicks": 0, "impressions": 0, "ctr": 0.0, "position": None}

    def last_date(self, start, end):
        rows = self.query(start, end, dims=["date"])
        return max(dt.date.fromisoformat(r["keys"][0]) for r in rows) if rows else None


def ga4_natural(s, start, end):
    r = s.post(f"https://analyticsdata.googleapis.com/v1beta/properties/{GA4}:runReport", json={
        "dateRanges": [{"startDate": str(start), "endDate": str(end)}], "dimensions": [{"name": "sessionMedium"}],
        "metrics": [{"name": "sessions"}], "limit": 1000})
    r.raise_for_status()
    rows = {x["dimensionValues"][0]["value"]: int(x["metricValues"][0]["value"]) for x in r.json().get("rows", [])}
    return {"total": sum(rows.values()), "natural": sum(rows.get(m, 0) for m in NATURAL_MEDIUMS),
            "organic": rows.get("organic", 0)}


def sheet_links(month_label, prev_label, month_start=None):
    """Haveababy 外鏈數量／域名。先讀 doc_data_table.py 存的 drafts/<月初>_Haveababy_table.json（排程先插表格），
    沒有才讀試算表（2026-11-18 起不再寫入，只剩舊資料）。"""
    saved = OUT_DIR / f"{month_start}_Haveababy_table.json"
    if month_start and saved.exists():
        t = json.loads(saved.read_text(encoding="utf-8"))
        num = lambda v: int(str(v).replace(",", "")) if str(v).replace(",", "").strip().isdigit() else None
        pick = lambda side: {"links": num(t[side].get("GSC外鏈數量")), "domains": num(t[side].get("GSC外鏈域名"))}
        return {"this": pick("this"), "prev": pick("prev"), "sheet_label": t["cur_label"]}
    from sheets_io import WEEKLY_SHEET, Sheets
    vals = Sheets().get(WEEKLY_SHEET, f"{WEEKLY_SHEET_TAB}!{SHEET_CELLS}")
    cell = lambda r, c: (vals[r][c] if r < len(vals) and c < len(vals[r]) else "") or ""
    num = lambda v: int(v) if str(v).strip().lstrip("-").isdigit() else None
    out = {"this": {}, "prev": {}, "sheet_label": str(cell(0, 0)).strip()}
    if out["sheet_label"] == month_label:
        cols = {"this": 0, "prev": 1}
    elif out["sheet_label"] == prev_label:      # 本月還沒填（排程沒跑或失敗）→ I 欄是上月
        cols = {"prev": 0}
    else:
        cols = {}
    for k, c in cols.items():
        out[k] = {"links": num(cell(SHEET_ROW["links"], c)), "domains": num(cell(SHEET_ROW["domains"], c))}
    return out


def holidays_in(start, end):
    if start.year not in HOLIDAYS:
        return None
    out = []
    for name, a, b in HOLIDAYS[start.year]:
        s, e = dt.date.fromisoformat(f"{start.year}-{a}"), dt.date.fromisoformat(f"{start.year}-{b}")
        if s <= end and e >= start:
            out.append({"name": name, "start": str(s), "end": str(e)})
    return out


def is_article(url):
    return "/posts/" in url


def days_with_rank(g, end, query, page):
    """月底最後 7 天有排名的天數（原 SOP：當週連續 5 天有排名數據才算穩定）。"""
    rows = g.query(end - dt.timedelta(days=6), end, dims=["date"], filters=[("query", query), ("page", page)])
    return len(rows)


def focus_word(g, word, cur, prev, cur_rows, prev_rows):
    """某個字的「查詢＋頁」數據：主攻頁＝上月曝光最多的頁面。"""
    pages = {}
    for tag, rows in (("prev", prev_rows), ("cur", cur_rows)):
        for r in rows:
            if r["keys"][0] == word:
                pages.setdefault(r["keys"][1], {})[tag] = r
    if not pages:
        return None
    page = max(pages, key=lambda p: (pages[p].get("prev", {}).get("impressions", 0), pages[p].get("cur", {}).get("impressions", 0)))
    blank = {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": None}
    return {"query": word, "page": page, "is_article": is_article(page),
            "cur": pages[page].get("cur", blank), "prev": pages[page].get("prev", blank),
            "days_with_rank_last7": days_with_rank(g, cur[1], word, page)}


MAIN_SHARE = 0.005   # 上月點擊佔整站 ≥ 0.5% 的文章才算「主要流量來源」


MAX_TARGETS = 5   # 符合條件就列，最多 5 篇（使用者 2026-11-05 決定；原本固定 3 篇）


def pick_targets(qp_cur, qp_prev, pg_cur, pg_prev, exclude_pages, n=MAX_TARGETS):
    """優化建議的對象：先看網頁、再看字（使用者 2026-11-05 定的做法）。
    1. 網頁（by URL）：上月點擊佔整站 ≥ 0.5% 的文章（上月主要流量來源），比較本月點擊、曝光、平均排名。
       第一優先＝三項同時衰退（點擊、曝光比上月少；平均排名變差 ≥ 0.5 名）；第二優先＝兩項衰退。同級依「文章點擊減少數」排序。
    2. 字：選出的文章裡，點擊減少最多的查詢（同數時看排名降幅），就是這篇要調整的字。
    exclude_pages：本月重點字的頁面、上月建議還在追蹤的頁面。"""
    total = sum(r["clicks"] for r in pg_prev) or 1
    pcur = {r["keys"][0]: r for r in pg_cur}
    pages = []
    for r in pg_prev:
        pg = r["keys"][0]
        if not is_article(pg) or pg in exclude_pages or r["clicks"] < total * MAIN_SHARE or r["position"] > 10:
            continue
        c = pcur.get(pg, {"clicks": 0, "impressions": 0, "position": None})
        click_down, impr_down = c["clicks"] < r["clicks"], c["impressions"] < r["impressions"]
        rank_down = (c["position"] or 100.0) - r["position"] >= 0.5
        downs = click_down + impr_down + rank_down
        left_page1 = (c["position"] or 100.0) > 10
        ctr_fall = ctr_collapse(r, c, 0.5)   # 網頁層級也套用點閱率大跌規則（點擊跌幅比曝光跌幅多 ≥ 20 個百分點）
        if downs < 2 and not left_page1 and not ctr_fall:
            continue
        why = "文章" + "、".join(w for w, f in (("點擊", click_down), ("曝光", impr_down), ("排名", rank_down)) if f) + "衰退"
        if left_page1:
            why += "，平均排名掉出首頁"
        if ctr_fall:
            why += f"，文章點閱率大跌（{r['ctr']:.1%} → {c.get('ctr', 0):.1%}）"
        pages.append({"page": pg, "tier": 1 if downs == 3 else 2, "why": why, "share": r["clicks"] / total,
                      "page_prev": r, "page_cur": c, "click_loss": r["clicks"] - c["clicks"],
                      "impr_loss": r["impressions"] - c["impressions"]})
    pages.sort(key=lambda x: (x["tier"], -x["click_loss"], -x["impr_loss"]))
    qcur = {tuple(r["keys"]): r for r in qp_cur}
    cands = []
    for pg in pages:
        qs = []
        for r in qp_prev:
            if r["keys"][1] != pg["page"]:
                continue
            if r["impressions"] < MIN_WORD_IMPR:
                continue
            c = qcur.get(tuple(r["keys"]))
            pos_now = c["position"] if c else 100.0
            cc = c or {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": None}
            key = matrix_key(r, cc)
            if key[2] != "-" and key[0] != "down":   # 點擊沒掉、排名也沒掉的字不算衰退
                continue
            qs.append({"query": r["keys"][0], "prev": r, "cur": cc, "matrix": list(key), "act": ACTION[key][0],
                       "drop": round(pos_now - r["position"], 1), "left_page1": r["position"] <= 10 < pos_now,
                       "loss": r["clicks"] - cc["clicks"]})
        if not qs:
            continue
        # 框架二：字＝該文章點擊減少最多的查詢（同數看排名降幅）；改法由對照表（框架三）決定，不影響選字
        qs.sort(key=lambda q: (-q["loss"], -q["drop"]))
        top = qs[0]
        head = max((r for r in qp_prev if r["keys"][1] == pg["page"]), key=lambda r: r["impressions"])["keys"][0]
        cands.append({**top, "page": pg["page"], "tier": pg["tier"], "why": pg["why"], "share": pg["share"], "head_query": head,
                      "page_prev": pg["page_prev"], "page_cur": pg["page_cur"],
                      "other_queries": [{k: q[k] for k in ("query", "prev", "cur", "loss")} for q in qs[1:3] if q["loss"] > 0]})
        if len(cands) == n:
            break
    by_query = {}
    for r in qp_cur:
        by_query.setdefault(r["keys"][0], []).append(r)
    for c in cands:   # 本月這個字改由站內其他頁面排名 → 可能是關鍵字蠶食（SOP 四-5）
        others = [r for r in by_query.get(c["query"], []) if r["keys"][1] != c["page"]
                  and r["impressions"] > c["cur"]["impressions"]]
        if others:
            o = max(others, key=lambda r: r["impressions"])
            c["cannibal"] = {"page": o["keys"][1], "impressions": o["impressions"], "position": o["position"]}
    return cands


def outline(url):
    """抓文章的標題結構、FAQ、schema（不需授權，公開網頁）。"""
    try:
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
    except Exception as e:
        return {"url": url, "error": str(e)}
    if "charset" not in r.headers.get("content-type", "").lower():   # 沒宣告編碼時 requests 會當成 latin-1
        r.encoding = "utf-8"
    t = r.text
    heads = [(m.group(1).lower(), re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m.group(2)))).strip())
             for m in re.finditer(r"<(h[1-3])[^>]*>(.*?)</\1>", t, re.S | re.I)]
    title = re.search(r"<title[^>]*>(.*?)</title>", t, re.S | re.I)
    types = set(re.findall(r'"@type"\s*:\s*"(\w+)"', t))
    h2 = [x for tag, x in heads if tag == "h2"]
    return {"url": url, "title": html.unescape(title.group(1).strip()) if title else "",
            "h1": [x for tag, x in heads if tag == "h1"], "h2": h2, "h3": [x for tag, x in heads if tag == "h3"],
            "has_faq": any(re.search(r"FAQ|常見問題|^Q\d", x, re.I) for _, x in heads),
            "faq_schema": "FAQPage" in types, "schema_types": sorted(types),
            "noindex": bool(re.search(r"<meta[^>]+name=[\"']robots[\"'][^>]+noindex", t, re.I)),
            "numbering_gap": numbering_gap(h2),
            "date_modified": (re.findall(r'"dateModified"\s*:\s*"([^"]+)"', t) or [None])[0]}


CN_NUM = "一二三四五六七八九十"


def numbering_gap(h2s):
    """H2 用「一、二、…」編號時找跳號（8 月建議過的那種問題）。"""
    nums = [CN_NUM.index(m.group(1)) + 1 for x in h2s if (m := re.match(r"^([一二三四五六七八九十])、", x))]
    return [f"{CN_NUM[a - 1]} → {CN_NUM[b - 1]}" for a, b in zip(nums, nums[1:]) if b != a + 1 and b <= 10]


def para_level(p):
    """段落視覺層級：照縮排算（過去報告的子項目有時在另一個清單裡，nestingLevel 不準）。"""
    ind = p["paragraphStyle"].get("indentStart", {}).get("magnitude", 0)
    return max(0, round(ind / 36) - 1)


def previous_report(s, month):
    """上月分析所在的文件：本月月報那週的前一份週報（每週複製，所以【HaveABaby】段落還是上月內容）。"""
    from copy_weekly_doc import doc_title, list_reports
    y, m = map(int, month.split("-"))
    last = month_range(y, m)[1]
    mon = last - dt.timedelta(days=last.weekday())
    title = doc_title(mon, mon + dt.timedelta(days=6))
    older = [f for f in list_reports(s) if f["name"] < title]
    return max(older, key=lambda f: f["name"]) if older else None


def last_month_suggestions(s, doc_id):
    """抓上月【HaveABaby】段落裡的文章建議：有文章連結的段落＋底下更深層的子項目，保留文字、連結與相對層級，之後原樣複製。"""
    d = s.get(f"{DOCS}/{doc_id}").json()
    sec = section_paragraphs(d)
    if "Claude 草稿" in json.dumps(sec["body"], ensure_ascii=False):
        return []
    out, cur, base = [], None, 0
    for el in sec["body"]:
        p = el["paragraph"]
        runs, links = [], []
        for e in p["elements"]:
            tr = e.get("textRun")
            if not tr:
                continue
            url = tr.get("textStyle", {}).get("link", {}).get("url", "")
            txt = tr["content"].replace("\n", "")
            if txt:
                runs.append((txt, ("link", url)) if url else (txt, None))
            if "haveababy.tw/posts/" in url:
                links.append(url)
        text = "".join(x for x, _ in runs).strip()
        lvl = para_level(p)
        if links:
            cur, base = {"urls": links, "paras": [(0, runs)], "text": text}, lvl
            out.append(cur)
        elif cur and text and (lvl > base or not p.get("bullet")):
            cur["paras"].append((max(1, lvl - base), runs))
            cur["text"] += " " + text
        elif p.get("bullet"):
            cur = None
    return out


def collect(month):
    y, m = map(int, month.split("-"))
    s = AuthorizedSession(load_credentials(allow_browser=False))
    g = GSC(s)
    (cs, ce), (ps, pe) = month_range(y, m), month_range(*prev_month(y, m))
    p2 = month_range(*prev_month(*prev_month(y, m)))
    warnings = []
    last = g.last_date(cs, ce)
    if last and last < ce:   # 資料還沒到月底（測試時）：跟上月同天數比較
        days = (last - cs).days + 1
        pe_cmp = min(pe, ps + dt.timedelta(days=days - 1))
        warnings.append(f"GSC 資料只到 {last}，改用 {cs}～{last} 比較上月同期 {ps}～{pe_cmp}；正式版請在月底 2 天後再跑")
        ce, pe = last, pe_cmp
        p2 = (p2[0], min(p2[1], p2[0] + dt.timedelta(days=days - 1)))
    cur, prev = (cs, ce), (ps, pe)

    site = {"cur": g.total(*cur), "prev": g.total(*prev), "prev2": g.total(*p2)}
    q_cur, q_prev = g.query(*cur, dims=["query"]), g.query(*prev, dims=["query"])
    qp_cur, qp_prev = g.query(*cur, dims=["query", "page"]), g.query(*prev, dims=["query", "page"])
    qc = {r["keys"][0]: r for r in q_cur}
    deltas = []
    for r in q_prev:
        c = qc.get(r["keys"][0], {"clicks": 0, "impressions": 0})
        deltas.append((r["keys"][0], c["clicks"] - r["clicks"], c["impressions"] - r["impressions"]))
    click_word = min(deltas, key=lambda x: x[1])[0]
    impr_word = min(deltas, key=lambda x: x[2])[0]
    words = {"click_drop": focus_word(g, click_word, cur, prev, qp_cur, qp_prev),
             "impr_drop": focus_word(g, impr_word, cur, prev, qp_cur, qp_prev)}
    for k, (w, dc, di) in (("click_drop", min(deltas, key=lambda x: x[1])), ("impr_drop", min(deltas, key=lambda x: x[2]))):
        if words[k]:
            words[k]["site_delta"] = {"clicks": dc, "impressions": di}
    exclude = {w["page"] for w in words.values() if w}
    src = previous_report(s, month)
    last_items = last_month_suggestions(s, src["id"]) if src else []
    exclude |= {u for it in last_items for u in it["urls"]}   # 上月建議還在追蹤的文章不重選，讓新對象涵蓋其他文章
    pg_cur, pg_prev = g.query(*cur, dims=["page"]), g.query(*prev, dims=["page"])
    targets = pick_targets(qp_cur, qp_prev, pg_cur, pg_prev, exclude)
    for t in targets:
        t["outline"] = outline(t["page"])
        t["days_with_rank_last7"] = days_with_rank(g, cur[1], t["query"], t["page"])

    trend = {}
    try:   # 搜尋熱度驗證（SPEC 數據分析框架一、三）：DataForSEO Google Trends＋Ads 月搜尋量
        import search_trend
        kws = [w["query"] for w in words.values() if w] + [t["query"] for t in targets] + [t["head_query"] for t in targets]
        trend = search_trend.summarize(list(dict.fromkeys(kws)), month)
    except Exception as e:
        warnings.append(f"DataForSEO 搜尋熱度沒抓到：{e}")

    ga = {"cur": ga4_natural(s, *cur), "prev": ga4_natural(s, *prev)}
    mlabel = lambda a, b: f"{a.month}/{a.day}-{b.month}/{b.day}"
    links = sheet_links(mlabel(*month_range(y, m)), mlabel(*month_range(*prev_month(y, m))), month_range(y, m)[0])

    followups = []
    if src:
        target_pages = {t["page"] for t in targets}
        for item in last_items:
            if item["urls"][0] in target_pages:   # 本月又選到同一篇 → 用本月的新建議，不重複
                continue
            followups.append({**item, "url": item["urls"][0], "source": src["name"], "outline": outline(item["urls"][0])})
    else:
        warnings.append("找不到上一份週報文件，沒有追蹤上月建議")

    hol = holidays_in(cs, month_range(y, m)[1])
    if hol is None:
        warnings.append(f"HOLIDAYS 沒有 {y} 年的連假表，請補 draft_analysis.py")
    return {"month": month, "cur": [str(cur[0]), str(cur[1])], "prev": [str(prev[0]), str(prev[1])],
            "prev2": [str(p2[0]), str(p2[1])], "country": COUNTRY, "site": site, "ga4": ga, "words": words,
            "targets": targets, "links": links, "holidays": {"cur": hol, "prev": holidays_in(*month_range(*prev_month(y, m)))},
            "followups": followups, "trend": trend, "warnings": warnings, "generated": str(dt.date.today())}


# ---------- 判讀 ----------

def direction(prev_pos, cur_pos, same_within):
    if prev_pos is None or cur_pos is None:
        return "down" if cur_pos is None else "up"
    d = round(prev_pos - cur_pos, 1)
    return "same" if abs(d) < same_within else ("up" if d > 0 else "down")


def sign(x):
    return "+" if x >= 0 else "-"


CTR_GAP = 0.2        # 點擊跌幅比曝光跌幅多 ≥ 20 個百分點，算「點閱率大跌」（使用者 2026-11-05 加的規則）
CTR_MIN_CLICKS = 5   # 上月點擊太少的字不判（雜訊）
CTR_MEANING = "點閱率大跌：點擊跌幅遠大於曝光跌幅，可能被 AI 摘要分走，或標題描述不夠吸睛"
CTR_ACTION = "查 SERP 有沒有 AI 摘要、是否引用我們，評估被分走的程度；調整標題、描述，內容補強放次要"


def ctr_collapse(prev, cur, same_within=1.0):
    """排名沒掉（上升或變動不到門檻）、點擊減少，而且點擊跌幅比曝光跌幅多 ≥ 20 個百分點
    → 對照表只看方向會判成「搜尋熱度降低」，實際是點閱率問題。"""
    if direction(prev["position"], cur["position"], same_within) == "down" or prev["clicks"] < CTR_MIN_CLICKS:
        return False
    if cur["clicks"] >= prev["clicks"] or not prev["impressions"]:
        return False
    click_fall = 1 - cur["clicks"] / prev["clicks"]
    impr_fall = 1 - cur["impressions"] / prev["impressions"]   # 曝光上升時是負數
    return click_fall - impr_fall >= CTR_GAP


def interpret(prev, cur, same_within):
    rk = direction(prev["position"], cur["position"], same_within)
    key = (rk, sign(cur["impressions"] - prev["impressions"]), sign(cur["clicks"] - prev["clicks"]))
    case = f"{RANK_WORD[rk]}＋曝光{'上升' if key[1] == '+' else '下降'}＋點擊{'上升' if key[2] == '+' else '下降'}"
    if ctr_collapse(prev, cur, same_within):
        return rk, case + f"（點閱率 {prev['ctr']:.1%} → {cur.get('ctr', 0):.1%}）", CTR_MEANING
    return rk, case, MATRIX[key]


def matrix_key(prev, cur, same_within=1.0):
    rk = direction(prev["position"], cur["position"], same_within)
    return (rk, sign(cur["impressions"] - prev["impressions"]), sign(cur["clicks"] - prev["clicks"]))


def heat_check(data, query, head=None, impr_prev=None, impr_cur=None):
    """搜尋熱度驗證的灰字：字本身 Trends 不夠就看主字；和 GSC 曝光方向矛盾時照實寫出來。"""
    import search_trend
    tr = data.get("trend") or {}
    if not tr:
        return ""
    used, t = query, tr.get(query)
    if (not t or t["trend"]["change"] is None or t["trend"]["missing_weeks"] >= 3) and head and head != query and tr.get(head):
        used, t = head, tr[head]
        lead = f"「{query}」搜尋量太小沒有 Trends 資料，改看文章主字「{head}」："
    else:
        lead = ""
    if not t:
        return ""
    txt = "搜尋熱度驗證：" + lead + search_trend.note(t, data["month"])
    ch = t["trend"]["change"]
    if t["trend"]["missing_weeks"] >= 3:   # 缺資料週數多，Trends 又是抽樣，不下結論
        return txt + "；資料不完整，只當參考，以 GSC 曝光為準"
    if ch is not None and impr_prev:
        gsc = impr_cur / impr_prev - 1
        if (ch <= -search_trend.HEAT_SAME and gsc > 0) or (ch >= search_trend.HEAT_SAME and gsc < -search_trend.HEAT_SAME):
            txt += f"；和 GSC 曝光（{gsc:+.0%}）方向相反，Trends 對小字不穩，以 GSC 曝光為準"
        elif ch <= -search_trend.HEAT_SAME:
            txt += "；搜尋熱度確實下降，點擊減少有一部分是需求變少"
        elif abs(ch) < search_trend.HEAT_SAME:
            txt += "；搜尋熱度持平，點擊減少不是需求變少"
    return txt


def stable_txt(n):
    return "月底最後 7 天都有排名" if n == 7 else f"月底最後 7 天有 {n} 天有排名"


def fmt_n(n):
    return f"{n:,}"


def chg(a, b):
    d = a - b
    return f"增加 {fmt_n(d)}" if d > 0 else (f"減少 {fmt_n(-d)}" if d < 0 else "持平")


def pos_text(prev, cur):
    if cur is None:
        return "本月沒有排名"
    if prev is None:
        return f"本月新出現，第 {cur} 名"
    d = round(prev - cur, 1)
    return f"上升 {d} 至第 {cur} 名" if d > 0 else (f"下降 {-d} 至第 {cur} 名" if d < 0 else f"持平在第 {cur} 名")


def short_md(d):
    d = dt.date.fromisoformat(d)
    return f"{d.month}/{d.day}"


def period(rng):
    return f"{short_md(rng[0])}～{short_md(rng[1])}"


# ---------- 草稿（段落樹） ----------
# 每個節點：(層級, [(文字, 樣式)])；樣式 None／"b" 粗體／"g" 灰字（數據、判讀依據）／"y" 黃底／("link", url)

def P(level, *runs):
    return (level, [r if isinstance(r, tuple) else (r, None) for r in runs])


def gray(level, label, text):
    return P(level, (f"{label}：{text}", "g"))


def rank_phrase(sv, fallback="無痕排名【待確認】"):
    """過去報告的寫法：「目前無痕第 3 名，有出現在 AIO」。"""
    txt = f"目前{sv.get('rank', fallback)}"
    if sv.get("aio") is True:
        txt += "，有出現在 AIO"
    return txt


def build(data, notes):
    """黑字＝給客戶看的文字，照過去報告的句型（結論併在句子裡，不列細數字）；
    灰字＝給自己和主管看的「數據」「判讀依據」，發到 Slack 前刪掉。"""
    serp, tnotes = notes.get("serp", {}), notes.get("targets", {})
    cur, prev = data["cur"], data["prev"]
    sc, sp = data["site"]["cur"], data["site"]["prev"]
    gc, gp = data["ga4"]["cur"], data["ga4"]["prev"]
    out = []

    # 1. 整體
    out.append(P(0, ("整體：", "b")))
    out.append(P(1, f"本月相較於上月整站曝光{chg(sc['impressions'], sp['impressions'])} 次，點擊{chg(sc['clicks'], sp['clicks'])} 次，"
                    f"平均排名{pos_text(sp['position'], sc['position'])}。"))
    rk, case, meaning = interpret(sp, sc, 0.5)
    hol, hol_prev = data["holidays"]["cur"], data["holidays"]["prev"] or []
    dropped = sc["clicks"] < sp["clicks"] or sc["impressions"] < sp["impressions"]
    if hol is None:
        say = "本月連假【待確認】，數據變化可持續觀察。"
    elif hol and dropped:
        say = f"本月遇{'、'.join(h['name'].removesuffix('日') for h in hol)}連假，數據相對上月下滑為合理狀態，可持續觀察。"
    elif dropped and rk != "down":
        say = "本月整站排名維持穩定，曝光與點擊下滑主要是搜尋熱度降低，可持續觀察。"
    elif dropped:
        say = "本月整站排名下滑，曝光與點擊跟著減少，下方針對排名下滑的文章提出優化建議。"
    else:
        say = "本月整體表現穩定成長，維持目前的優化方向。"
    out.append(P(2, say))
    days_c = (dt.date.fromisoformat(cur[1]) - dt.date.fromisoformat(cur[0])).days + 1
    days_p = (dt.date.fromisoformat(prev[1]) - dt.date.fromisoformat(prev[0])).days + 1
    ga_txt = ""
    if gp["organic"]:
        pct = (gc["organic"] - gp["organic"]) / gp["organic"] * 100
        same_dir = (gc["organic"] >= gp["organic"]) == (sc["clicks"] >= sp["clicks"])
        ga_txt = (f"；GA4 organic 工作階段 {fmt_n(gp['organic'])} → {fmt_n(gc['organic'])}（{pct:+.1f}%），"
                  f"{'和 GSC 點擊同方向' if same_dir else '和 GSC 點擊方向不同，請確認追蹤'}")
    hol_txt = "、".join(f"{h['name']} {short_md(h['start'])}～{short_md(h['end'])}" for h in hol or []) or "無"
    prev_hol = f"；上月連假：{'、'.join(h['name'] for h in hol_prev)}" if hol_prev else ""
    out.append(gray(3, "數據", f"GSC 台灣，本月 {period(cur)}（{days_c} 天）vs 上月 {period(prev)}（{days_p} 天），"
                              f"點閱率 {sp['ctr']:.2%} → {sc['ctr']:.2%}{ga_txt}；本月連假：{hol_txt}{prev_hol}。"))
    out.append(gray(3, "判讀依據", f"SOP 四-4（排名、曝光、點擊的關係）{case} →「{meaning}」（整站平均排名變動不到 0.5 名視為不變）；"
                                 "SOP 三-4 下降原因先看演算法、文章表現、連假。演算法更新請到 Ahrefs 時間軸確認。"))

    # 2. 重點大字：點擊、曝光減少最多的字
    for key, what in (("click_drop", "點擊"), ("impr_drop", "曝光")):
        w = data["words"].get(key)
        if not w:
            continue
        sv = serp.get(w["query"], {})
        c, p = w["cur"], w["prev"]
        rk, case, meaning = interpret(p, c, 1.0)
        tail = []
        if not w["is_article"]:
            tail.append("非 SEO 文章頁面")
        if sv.get("comment"):
            tail.append(sv["comment"])
        elif w["days_with_rank_last7"] < 5:
            tail.append("排名數據較不穩定，可持續觀察")
        elif rk == "down":
            tail.append("排名有下滑，建議安排大小改")
        elif "不夠吸睛" in meaning:
            tail.append("排名穩定但點擊率下降，建議可以調整標題與描述，提高點擊")
        elif "熱度降低" in meaning:
            tail.append("排名沒有明顯變化，主要是搜尋熱度趨緩，可持續觀察")
        out.append(P(2, f"與上月相比{what}減少最多的字為「{w['query']}」，{rank_phrase(sv)}"
                        + ("，" + "，".join(tail) if tail else "") + "。"))
        d = w["site_delta"]["clicks" if what == "點擊" else "impressions"]
        extra = []
        if c["position"] and c["position"] <= 10 and c["ctr"] < 0.005:
            extra.append("排名在第一頁但點閱率低於 0.5%，請無痕確認是否為圖片排名（SOP 四-5）")
        if "不夠吸睛" in meaning and sv.get("aio"):
            extra.append("這個字有出現 AIO，點擊也可能被 AIO 分走")
        hc = heat_check(data, w["query"], None, p["impressions"], c["impressions"])
        if hc:
            extra.append(hc)
        out.append(gray(3, "數據", f"整站{what}{chg(d, 0)} 次；"
                                  f"查詢＋頁（{w['page'].replace('https://haveababy.tw', '')}）排名 {p['position']} → {c['position']}，"
                                  f"曝光 {fmt_n(p['impressions'])} → {fmt_n(c['impressions'])}，點擊 {fmt_n(p['clicks'])} → {fmt_n(c['clicks'])}，"
                                  f"點閱率 {p['ctr']:.1%} → {c['ctr']:.1%}；{stable_txt(w['days_with_rank_last7'])}"
                                  + ("；" + "；".join(extra) if extra else "") + "。"))
        out.append(gray(3, "判讀依據", f"SOP 五「查詢＋頁」完全相符看主攻頁數據；SOP 四-4 {case} →「{meaning}」（排名變動不到 1 名視為不變）；"
                                     "SOP 四-5 當週連續 5 天有排名才算穩定。"))

    # 外鏈
    lt = {**(data["links"].get("this") or {}), **notes.get("links", {})}
    lp = data["links"].get("prev") or {}

    def lk(k):
        v, pv = lt.get(k), lp.get(k)
        if v is None:
            return "【待填】"
        if pv is None:
            return f"{fmt_n(v)} 個"
        return f"{fmt_n(v)} 個（{'-' if v == pv else f'{v - pv:+,}'}）"
    out.append(P(1, f"外鏈數量 {lk('links')}，外鏈域名 {lk('domains')}。"))
    if lt.get("links") is not None and lp.get("links"):
        rate = (lt["links"] - lp["links"]) / lp["links"]
        if rate <= -0.15:
            c = "外鏈數量降幅大，先對照 Welly、Welly HK 是否同時大降；大家一起降通常之後會回升，暫時觀察。"
        elif lt.get("domains") is not None and lp.get("domains") is not None and lt["domains"] < lp["domains"]:
            c = "外鏈域名減少，到外鏈域名紀錄比對遺失的域名，自建或高相關的標紅底並註解。"
        else:
            c = "外鏈數量與域名變化不大。"
        out.append(gray(2, "判讀依據", f"{c}（SOP 三-3：外鏈收錄 1 週～2 個月不等；單一網站大降先看其他網站是否一樣）"))

    # 3. 優化建議
    out.append(P(1, "優化建議："))
    for t in data["targets"]:
        o, n = t.get("outline", {}), tnotes.get(t["page"], {})
        sv = serp.get(t["query"], {})
        title = (o.get("h1") or [o.get("title") or t["query"]])[0]
        c, p = t["cur"], t["prev"]
        if sv.get("rank"):
            pos = f"（目前{sv['rank']}）"
        elif t["left_page1"]:
            pos = "（目前掉出首頁，無痕排名【待確認】）"
        else:
            pos = "（無痕排名【待確認】）"
        intent = n.get("intent")
        lead = (f"，從 SERP 首頁文章判斷，用戶想了解「{intent}」，建議優化：" if intent
                else "，從 SERP 觀察其他首頁文章，建議可以優化以下：")
        kinds = [w for w in ("點擊", "曝光", "排名", "點閱率") if w in t.get("why", "曝光、排名")][:2]   # 過去報告句型：「在點擊及排名變化較大的」
        out.append(P(2, f"其他近期在{'及'.join(kinds)}變化較大的還有「", t["query"], "」，以「", (title, ("link", t["page"])),
                     f"」主題的文章獲得排名{pos}{lead}"))
        sugg = list(n.get("suggestions", []))
        if not sugg:   # 沒有 SERP 比對時，先給文章結構上的檢查結果
            if not o.get("has_faq"):
                sugg.append("新增 FAQ 段落，並建立 schema。")
            elif not o.get("faq_schema"):
                sugg.append("FAQ 建立 schema，增加被 AIO 引用的機會。")
            if o.get("h1") and t["query"].replace(" ", "") not in o["h1"][0].replace(" ", ""):
                sugg.append(f"H1 標題：可評估納入「{t['query']}」。")
            for gap in o.get("numbering_gap", []):
                sugg.append(f"H2 標題有跳號（{gap}），建議修正。")
            sugg.append("【待補】對照 SERP 首頁文章，列出 HaveABaby 缺少的段落。")
        for x in sugg:
            out.append(P(3, x))
        if t.get("cannibal"):
            cb = t["cannibal"]
            out.append(P(3, "這個字本月改由「", (cb["page"].replace("https://haveababy.tw", ""), ("link", cb["page"])),
                         "」獲得排名，建議確認兩篇文章的主攻字，避免互相競爭。"))
        if t.get("page_prev"):
            pp_, pc_ = t["page_prev"], t["page_cur"]
            facts = (f"文章整篇（上月點擊佔整站 {t['share']:.1%}）點擊 {fmt_n(pp_['clicks'])} → {fmt_n(pc_['clicks'])}，"
                     f"曝光 {fmt_n(pp_['impressions'])} → {fmt_n(pc_['impressions'])}，平均排名 {pp_['position']} → {pc_['position'] or '無'}；")
            if t.get("other_queries"):
                facts += "其他衰退的字：" + "、".join(f"「{q['query']}」點擊 {q['prev']['clicks']} → {q['cur']['clicks']}" for q in t["other_queries"]) + "；"
        else:
            facts = ""
        facts += (f"查詢＋頁 排名 {p['position']} → {c['position'] if c['position'] else '無'}（下降 {t['drop']} 名），"
                 f"曝光 {fmt_n(p['impressions'])} → {fmt_n(c['impressions'])}，點擊 {fmt_n(p['clicks'])} → {fmt_n(c['clicks'])}；"
                 f"{stable_txt(t['days_with_rank_last7'])}；")
        if o.get("error"):
            facts += f"文章抓取失敗：{o['error']}"
        else:
            facts += (f"文章現況 FAQ {'有' if o.get('has_faq') else '無'}、FAQPage schema {'有' if o.get('faq_schema') else '無'}、"
                      f"H2 {len(o.get('h2', []))} 個")
        if n.get("evidence"):
            facts += f"；SERP 觀察：{n['evidence']}"
        hc = heat_check(data, t["query"], t.get("head_query"), p["impressions"], c["impressions"])
        if hc:
            facts += f"；{hc}"
        out.append(gray(3, "數據", facts + "。"))
        key = tuple(t["matrix"]) if t.get("matrix") else matrix_key(p, c)
        rk, case, meaning = interpret(p, c, 1.0)
        action = CTR_ACTION if meaning == CTR_MEANING else ACTION[key][1]
        basis = (f"SOP 四-4 對照表：{case} →「{meaning}」，該怎麼做：{action}（單一字排名變動不到 1 名視為不變；"
                 "點擊跌幅比曝光跌幅多 ≥ 20 個百分點改判點閱率問題）")
        if key[0] != "down" and key[2] == "-" and meaning != CTR_MEANING:
            basis += "；排名沒掉、點擊減少 → 看 SERP 有沒有 AI 摘要，評估點擊是否被 AI 摘要分走"
        if t.get("cannibal"):
            basis += "；SOP 四-5 排名大跌先查關鍵字蠶食（這個字本月改由站內其他頁面排名）"
        if o.get("noindex"):
            basis += "；⚠ 頁面設了 noindex，先確認是否誤設"
        if p.get("position") and p["position"] <= 10 and p.get("ctr", 1) < 0.005:
            basis += "；首頁但點閱率 < 0.5%，查是否被圖片排名佔走版面"
        tier = "第一優先：三項同時衰退" if t.get("tier") == 1 else "第二優先：兩項衰退、掉出首頁或點閱率大跌"
        basis += (f"。入選原因：{t.get('why', '')}（{tier}）。"
                  "選文條件（SPEC 數據分析框架二）：上月點擊佔整站 ≥ 0.5%、上月在首頁的文章，三項都衰退優先、再來兩項衰退、掉出首頁或點閱率大跌，"
                  "同級依文章點擊減少數排序；字取該文章點擊減少最多的查詢，再用對照表判斷原因與改法。")
        out.append(gray(3, "判讀依據", basis))

    month_start = dt.date.fromisoformat(cur[0])
    for f in data.get("followups", []):
        o = f["outline"]
        if o.get("error"):
            continue
        pending = []
        if "FAQ" in f["text"] and not o.get("has_faq"):
            pending.append("FAQ 段落")
        if ("FAQ" in f["text"] or "schema" in f["text"]) and not o.get("faq_schema"):
            pending.append("FAQPage schema")
        mod = o.get("date_modified")
        mod_d = dt.date.fromisoformat(mod[:10]) if mod else None
        untouched = mod_d is not None and mod_d < month_start
        if not pending and mod_d and not untouched:
            continue   # 已調整過，不再重複
        for rel, runs in f["paras"]:   # 原樣複製上月的建議（文字、連結、層級）
            out.append((2 + rel, [(r[0], tuple(r[1]) if isinstance(r[1], list) else r[1]) for r in runs]))
        why = []
        if untouched:
            why.append(f"文章最後更新是 {mod[:10]}，{month_start.month} 月沒有更新")
        if pending:
            why.append(f"{'、'.join(pending)} 仍未建立")
        reason = "；".join(why) if why else "無法自動判斷有沒有修改，請到文章確認"
        out.append(P(3, (f"上月建議尚未修改（{reason}），所以這次可以繼續放。（交接：客戶不一定照做，上月建議可以重複給）", "g")))
    for x in notes.get("extra", []):
        out.append(P(2, x))

    s2 = data["site"]["prev2"]
    trend_down = sc["impressions"] < sp["impressions"] < s2["impressions"]
    out.append(P(2, "近 3 個月整站曝光呈現下滑趨勢，建議優先處理上述文章，並持續觀察。" if trend_down
                 else "近 3 個月的整體趨勢沒有明顯的大幅變動，建議可以持續優化文章並觀察。"))
    out.append(gray(3, "數據", f"近 3 個月整站曝光 {fmt_n(s2['impressions'])} → {fmt_n(sp['impressions'])} → {fmt_n(sc['impressions'])}，"
                              f"點擊 {fmt_n(s2['clicks'])} → {fmt_n(sp['clicks'])} → {fmt_n(sc['clicks'])}，"
                              f"平均排名 {s2['position']} → {sp['position']} → {sc['position']}。"))
    out.append(gray(3, "判讀依據", "SOP 四-4 第 4 點：考量不同時間外在環境對搜尋熱度的影響，拉長期間看趨勢。"))
    return out


# ---------- Google 文件 ----------

def section_paragraphs(d):
    """【HaveABaby】標題之後、「本月 vs 上月」之前的段落（不含緊貼在前面的空段落）。"""
    content = d["body"]["content"]
    text = lambda el: "".join(e.get("textRun", {}).get("content", "") for e in el.get("paragraph", {}).get("elements", [])).strip()
    head = next((i for i, el in enumerate(content) if "【HaveABaby】" in text(el)), None)
    if head is None:
        raise SystemExit("找不到【HaveABaby】標題")
    heading = lambda el: el.get("paragraph", {}).get("paragraphStyle", {}).get("namedStyleType", "").startswith("HEADING") and "【" in text(el)
    end = next((i for i in range(head + 1, len(content)) if text(content[i]) == "本月 vs 上月" or heading(content[i])), None)
    if end is None or text(content[end]) != "本月 vs 上月":
        raise SystemExit("【HaveABaby】段落裡找不到「本月 vs 上月」，版面和預期不同，請人工處理")
    stop = end
    while stop - 1 > head and not text(content[stop - 1]) and "inlineObjectElement" not in json.dumps(content[stop - 1]):
        stop -= 1
    body = [el for el in content[head + 1:stop] if "paragraph" in el]
    if any("table" in el for el in content[head + 1:stop]):
        raise SystemExit("【HaveABaby】段落裡有表格，版面和預期不同，請人工處理")
    return {"heading": text(content[head]), "start": content[head]["endIndex"],
            "end": content[stop]["startIndex"], "body": body}


def utf16_len(s):
    return len(s.encode("utf-16-le")) // 2


def _pt(x):
    return {"magnitude": x, "unit": "PT"}


def requests_for(nodes, header, at):
    """先刪舊內容，再一次插入全部文字（每段前面用 tab 表示層級），建立項目符號，最後套樣式。
    層級是 None 的段落不加項目符號、不縮排（例如【舊站】【新站】小標、空行）。"""
    lines = [header] + ["\t" * (lvl or 0) + "".join(t for t, _ in runs) for lvl, runs in nodes]
    text = "\n".join(lines) + "\n"
    reqs = [{"insertText": {"location": {"index": at}, "text": text}}]
    total = utf16_len(text)
    reqs.append({"updateTextStyle": {"range": {"startIndex": at, "endIndex": at + total},
                                     "textStyle": {}, "fields": "bold,italic,link,foregroundColor,underline,backgroundColor"}})
    reqs.append({"updateParagraphStyle": {"range": {"startIndex": at, "endIndex": at + total},
                                          "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"}, "fields": "namedStyleType"}})
    bullets_start = at + utf16_len(header) + 1
    # 插入點後面的段落如果本來就有項目符號，新段落會沿用它，行首 tab 就不會被轉成層級 → 先全部拿掉再建立
    reqs.append({"deleteParagraphBullets": {"range": {"startIndex": at, "endIndex": at + total - 1}}})
    # 拿掉項目符號時 Docs 會補縮排保留原本的層級視覺（例如 108pt），建立項目符號又往右疊 → 先把縮排歸零
    reqs.append({"updateParagraphStyle": {"range": {"startIndex": at, "endIndex": at + total},
                                          "paragraphStyle": {"indentStart": _pt(0), "indentFirstLine": _pt(0)},
                                          "fields": "indentStart,indentFirstLine"}})
    reqs.append({"createParagraphBullets": {"range": {"startIndex": bullets_start, "endIndex": at + total - 1},
                                            "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"}})
    # createParagraphBullets 會把行首 tab 拿掉，之後的位置要用「去掉 tab」的長度算
    styles = [{"updateTextStyle": {"range": {"startIndex": at, "endIndex": at + utf16_len(header)},
                                   "textStyle": {"italic": True, "foregroundColor": {"color": {"rgbColor": {"red": 0.6, "green": 0.6, "blue": 0.6}}}},
                                   "fields": "italic,foregroundColor"}}]
    pos = bullets_start
    for lvl, runs in nodes:
        # 縮排照人工範本：第 0 層 18／36pt，每多一層 +36pt
        para_len = sum(utf16_len(t) for t, _ in runs) + 1
        prange = {"startIndex": pos, "endIndex": pos + para_len}
        if lvl is None:   # 不要項目符號：拿掉後縮排歸零（拿掉時 Docs 會自己補縮排）
            styles.append({"deleteParagraphBullets": {"range": prange}})
            first, start = 0, 0
        else:
            first, start = 18 + 36 * lvl, 36 + 36 * lvl
        styles.append({"updateParagraphStyle": {"range": prange,
                                                "paragraphStyle": {"indentFirstLine": _pt(first), "indentStart": _pt(start)},
                                                "fields": "indentFirstLine,indentStart"}})
        for t, st in runs:
            n = utf16_len(t)
            rng = {"startIndex": pos, "endIndex": pos + n}
            if not n:   # 空行：Docs 不接受空範圍的樣式
                continue
            if st == "b":
                styles.append({"updateTextStyle": {"range": rng, "textStyle": {"bold": True}, "fields": "bold"}})
            elif st == "y":   # 黃底（Welly／Welly HK 報告的黑字都標黃底）
                styles.append({"updateTextStyle": {"range": rng, "textStyle": {"backgroundColor": {"color": {"rgbColor": {"red": 1, "green": 1, "blue": 0}}}},
                                                   "fields": "backgroundColor"}})
            elif st == "g":
                styles.append({"updateTextStyle": {"range": rng, "textStyle": {"foregroundColor": {"color": {"rgbColor": {"red": 0.6, "green": 0.6, "blue": 0.6}}}},
                                                   "fields": "foregroundColor"}})
            elif isinstance(st, tuple) and st[0] == "link":
                styles.append({"updateTextStyle": {"range": rng, "textStyle": {
                    "link": {"url": st[1]}, "underline": True,
                    "foregroundColor": {"color": {"rgbColor": {"red": 0.067, "green": 0.333, "blue": 0.8}}}},
                    "fields": "link,underline,foregroundColor"}})
            pos += n
        pos += 1   # 換行
    return reqs, styles


def check_writable(s, doc_id, month, force):
    meta = s.get(f"{DRIVE}/{doc_id}", params={"fields": "name,capabilities/canEdit", "supportsAllDrives": True}).json()
    name = meta.get("name", "")
    if not meta.get("capabilities", {}).get("canEdit"):
        raise SystemExit(f"沒有編輯權限：{name}（drive.file 只能改本程式建立的文件）")
    if not name.startswith("[TEST]"):
        m = TITLE_RE.match(name)
        if not m:
            raise SystemExit(f"拒絕寫入：「{name}」不是週報文件，也不是 [TEST] 副本")
        mon = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if mon < FIRST_WEEK:
            raise SystemExit(f"拒絕寫入：{name} 早於 {FIRST_WEEK} 那週（同事的紀錄）")
        monthly = plan(mon + dt.timedelta(days=7 + 3))["monthly"]
        if monthly != tuple(map(int, month.split("-"))):
            raise SystemExit(f"拒絕寫入：{name} 那週的月報是 {monthly}，不是 {month}")
    d = s.get(f"{DOCS}/{doc_id}").json()
    sec = section_paragraphs(d)
    y, mm = map(int, month.split("-"))
    ms, me = month_range(y, mm)
    if f"{ms.month}/{ms.day}-{me.month}/{me.day}" not in sec["heading"]:
        raise SystemExit(f"標題是「{sec['heading']}」，不是 {month} 月報（先跑 copy_weekly_doc.py 改標題）")
    body_text = "".join(e.get("textRun", {}).get("content", "") for el in sec["body"] for e in el["paragraph"]["elements"])
    if ("Claude 草稿" in body_text) and not force:
        raise SystemExit("段落裡已經有 Claude 草稿（可能已被修改），不覆蓋；確定要重寫請加 --force")
    return name, sec


def write(s, doc_id, month, nodes, data, notes, dry_run, force):
    name, sec = check_writable(s, doc_id, month, force)
    header = (f"{MARKER}｜{data['generated']} 產生〕GSC 台灣 {period(data['cur'])} vs {period(data['prev'])}。"
              "請檢查數據、判讀依據與結論後再發到 Slack；發到 Slack 前刪掉這行和灰字的「判讀依據」。")
    if notes.get("serp_source"):
        header += f" SERP：{notes['serp_source']}。"
    for w in data["warnings"]:
        header += f" ⚠ {w}"
    reqs, styles = requests_for(nodes, header, sec["start"])
    if sec["end"] > sec["start"]:
        reqs.insert(0, {"deleteContentRange": {"range": {"startIndex": sec["start"], "endIndex": sec["end"]}}})
    print(f"文件：{name}\n段落：{sec['heading']}（取代 {sec['start']}～{sec['end']}）")
    if dry_run:
        return
    r = s.post(f"{DOCS}/{doc_id}:batchUpdate", json={"requests": reqs})
    if not r.ok:
        raise SystemExit(f"寫入失敗：{r.status_code} {r.text[:500]}")
    r = s.post(f"{DOCS}/{doc_id}:batchUpdate", json={"requests": styles})
    if not r.ok:
        raise SystemExit(f"套樣式失敗：{r.status_code} {r.text[:500]}")
    print(f"已寫入：https://docs.google.com/document/d/{doc_id}/edit")


def to_text(nodes):
    def run(t, st):
        return f"[{t}]({st[1]})" if isinstance(st, tuple) else t
    return "\n".join(("" if lvl is None else "  " * lvl + "- ") + "".join(run(t, st) for t, st in runs)
                     for lvl, runs in nodes)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--month", required=True)
    o = sub.add_parser("outline")
    o.add_argument("urls", nargs="+")
    w = sub.add_parser("write")
    w.add_argument("--month", required=True)
    w.add_argument("--doc", required=True)
    w.add_argument("--notes")
    w.add_argument("--recollect", action="store_true", help="不用已存的 JSON，重新抓數據")
    w.add_argument("--dry-run", action="store_true")
    w.add_argument("--force", action="store_true")
    t = sub.add_parser("test-copy")
    t.add_argument("--source", required=True)
    a = ap.parse_args()

    if a.cmd == "outline":
        for u in a.urls:
            print(json.dumps(outline(u), ensure_ascii=False, indent=2))
        return

    s = AuthorizedSession(load_credentials(allow_browser=False, scopes=LOCAL_SCOPES))
    if a.cmd == "test-copy":
        src = s.get(f"{DRIVE}/{a.source}", params={"fields": "name"}).json()["name"]
        r = s.post(f"{DRIVE}/{a.source}/copy", json={"name": f"[TEST] {src}", "parents": ["root"]}, params={"fields": "id,name"})
        r.raise_for_status()
        print(f"{r.json()['name']}\nhttps://docs.google.com/document/d/{r.json()['id']}/edit\nID {r.json()['id']}")
        return

    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"{a.month}_Haveababy_analysis.json"
    if a.cmd == "collect" or a.recollect or not path.exists():
        data = collect(a.month)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"數據：{path}")
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    if a.cmd == "collect":
        qs = [w["query"] for w in data["words"].values() if w] + [t["query"] for t in data["targets"]]
        print("要查 SERP（無痕排名、AIO、前幾名文章）的字：" + "、".join(dict.fromkeys(qs)))
        for t in data["targets"]:
            print(f"  優化對象：{t['query']} → {t['page']}（排名 {t['prev']['position']} → {t['cur']['position']}，"
                  f"點擊 {t['prev']['clicks']} → {t['cur']['clicks']}）判讀：{interpret(t['prev'], t['cur'], 1.0)[2]}")
        for w_ in data["warnings"]:
            print("⚠", w_)
        return
    notes = json.loads(Path(a.notes).read_text(encoding="utf-8")) if a.notes else {}
    nodes = build(data, notes)
    print(to_text(nodes))
    write(s, a.doc, a.month, nodes, data, notes, a.dry_run, a.force)


if __name__ == "__main__":
    main()
