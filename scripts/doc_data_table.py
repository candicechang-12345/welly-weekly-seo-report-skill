"""把一個品牌的 GA4、GSC、月累與人工項目整理成彩色表格，直接插進當週報告文件（取代原本貼的「全品項數據週報」截圖）。

2026-11-18 起不再寫「全品項數據週報」試算表：
  - 本期、上期的 GA4 四格、GSC 四項、月累都用 API 現抓（算法同舊 fill_weekly_block.py，見 metrics.py）。
  - 良好網站比例、外鏈數量／域名（GSC 介面）、DR／UR（Ahrefs）由排程帶入；上期值讀文件裡上週那張表，
    沒有表時才讀試算表（唯讀）。
  - 表格配色沿用試算表：Welly／WellyHK／Welly新站 表頭黃（#FDDA5A、#FFD966），HaveAbaby 淺藍（#C9DAF8）。
    「變化」欄變好綠字、變差紅字（排名、跳出率越低越好）。

位置：品牌段落「本週 vs 上週」／「本月 vs 上月」之後。同品牌已有表 → 原地換新；Welly新站 接在 Welly 表後面；
都沒有 → 取代該段落裡高度 > 200 的圖片（舊的試算表截圖），GSC 指標卡片截圖（較矮）不動。

用法（工作目錄 scripts）：
  python doc_data_table.py Welly --week 2026-11-09 --doc <文件ID> --cwv 良好 --links 3077 --domains 275 --dr 47 --ur 22 [--dry-run]
  python doc_data_table.py WellyHK --week 2026-11-30 --month 2026-11 --doc <文件ID> ...
寫入限制同 draft_welly.py：[TEST] 副本，或 copy_weekly_doc.py 建立的該週報告文件。
輸出 DOMAINS_CHANGED 行（外鏈域名有變）與 WARNING 行（GA4 缺資料）；數字另存 drafts/<本期起日>_<品牌>_table.json。
"""

import argparse
import datetime as dt
import json
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession

from copy_weekly_doc import DOCS
from draft_welly import check_doc
from metrics import (BRANDS, MANUAL, ROWS, ga4_daily_sum, ga4_sheet_method, gsc_totals, label, mtd_ranges,
                     periods, row_numbers)
from welly_auth import LOCAL_SCOPES, load_credentials

OUT_DIR = Path(__file__).resolve().parent.parent / "drafts"
TITLES = {"Welly": "Welly", "WellyNew": "Welly新站", "WellyHK": "WellyHK", "Haveababy": "HaveAbaby"}
SECTIONS = {"Welly": ("【Welly】", "本週 vs 上週"), "WellyNew": ("【Welly】", "本週 vs 上週"),
            "WellyHK": ("【Welly HK】", "本月 vs 上月"), "Haveababy": ("【HaveABaby】", "本月 vs 上月")}
ORDER = ["Welly", "WellyNew"]          # 同一段落裡的表格順序
COLORS = {"Haveababy": ("#C9DAF8", "#C9DAF8")}
DEFAULT_COLORS = ("#FDDA5A", "#FFD966")  # (品牌名格, 日期／變化格)
GOOD, BAD = "#38761D", "#CC0000"
WIDTHS = [150, 100, 100, 100]          # pt，合計約等於頁面內容寬 451pt
COUNTS = {"總工作階段", "自然流量工作階段", "點擊量", "曝光量", "本月累積非付費流量"}
ABS = {"GSC外鏈域名", "GSC外鏈數量", "DR", "UR"}


# ---------- 數字 ----------

def to_num(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).replace(",", "").strip()
    try:
        return float(s[:-1]) / 100 if s.endswith("%") else float(s)
    except ValueError:
        return None


def secs(v):
    if not v or ":" not in str(v):
        return None
    m, s = str(v).split(":")
    return int(m) * 60 + int(s)


def fmt(name, v):
    if v in (None, ""):
        return ""
    if name == "良好網站比例" or name == "自然流量平均參與時間":
        return str(v)
    n = to_num(v)
    if n is None:
        return str(v)
    if name in ("自然流量跳出率", "平均點閱率"):
        return f"{n * 100:.1f}%"
    if name == "平均排序":
        return f"{n:.1f}"
    if name in ("DR", "UR"):
        return f"{n:g}"
    return f"{int(round(n)):,}"


def change(name, cur, prev):
    """回傳 (文字, 1 變好／-1 變差／0)。"""
    if name == "良好網站比例":
        return ("", 0) if not cur or not prev or cur == prev else ("有變動", 0)
    if name == "自然流量平均參與時間":
        c, p = secs(cur), secs(prev)
        if c is None or p is None:
            return "", 0
        d = c - p
        return (f"{'+' if d >= 0 else '-'}{abs(d) // 60}:{abs(d) % 60:02d}", (d > 0) - (d < 0))
    c, p = to_num(cur), to_num(prev)
    if c is None or p is None:
        return "", 0
    if name == "平均排序":
        d = round(round(c, 1) - round(p, 1), 1)
        return ("不變", 0) if d == 0 else (f"上升 {abs(d):g}", 1) if d < 0 else (f"下降 {d:g}", -1)
    if name in ("自然流量跳出率", "平均點閱率"):
        d = round((c - p) * 100, 1)
        good = -1 if name == "自然流量跳出率" else 1
        return ("持平", 0) if d == 0 else (f"{d:+.1f} 個百分點", good * (1 if d > 0 else -1))
    if name in ABS:
        d = round(c - p, 1)
        return ("持平", 0) if d == 0 else (f"{d:+g}", 1 if d > 0 else -1)
    if p == 0:
        return "", 0
    pct = (c - p) / p
    return (f"{pct:+.1%}", (pct > 0) - (pct < 0))


# ---------- 文件結構 ----------

def ptext(el):
    return "".join(e.get("textRun", {}).get("content", "") for e in el.get("paragraph", {}).get("elements", [])).strip()


def cell_text(cell):
    return "".join(ptext(p) for p in cell.get("content", []))


def table_grid(el):
    return [[cell_text(c) for c in r["tableCells"]] for r in el["table"]["tableRows"]]


def is_heading(el):
    return el.get("paragraph", {}).get("paragraphStyle", {}).get("namedStyleType", "").startswith("HEADING")


def image_height(d, el):
    for e in el.get("paragraph", {}).get("elements", []):
        oid = e.get("inlineObjectElement", {}).get("inlineObjectId")
        if oid:
            size = d["inlineObjects"][oid]["inlineObjectProperties"]["embeddedObject"].get("size", {})
            return size.get("height", {}).get("magnitude", 0)
    return None


def region(d, brand):
    """品牌段落「vs」那行之後、下一個標題之前的元素。"""
    title, vs = SECTIONS[brand]
    content = d["body"]["content"]
    head = next((i for i, el in enumerate(content) if is_heading(el) and ptext(el).startswith(title)), None)
    if head is None:
        raise SystemExit(f"找不到{title}標題")
    end = next((i for i in range(head + 1, len(content)) if is_heading(content[i])), len(content))
    vs_i = next((i for i in range(head + 1, end) if ptext(content[i]) == vs), None)
    if vs_i is None:
        raise SystemExit(f"{title}段落裡找不到「{vs}」，版面和預期不同，請人工處理")
    return content[vs_i + 1:end], content[vs_i]


def find_tables(elements):
    return {t: el for el in elements if "table" in el
            for t in [table_grid(el)[0][0] if el["table"]["tableRows"] else ""] if t in TITLES.values()}


def placement(d, brand):
    """回傳 (插入位置, 要刪的範圍或 None, 文件裡原本的表格內容或 None)。"""
    elements, vs_el = region(d, brand)
    tables = find_tables(elements)
    mine = tables.get(TITLES[brand])
    if mine:
        # insertTable 會在表格前多插一個空段落；重跑時一起刪，空行才不會越疊越多
        i = elements.index(mine)
        before = elements[i - 1] if i > 0 else None
        start = before["startIndex"] if before and "paragraph" in before and not ptext(before) \
            and image_height(d, before) is None else mine["startIndex"]
        return start, (start, mine["endIndex"]), table_grid(mine)
    others = [TITLES[b] for b in ORDER if b != brand and TITLES[b] in tables]
    if others and brand in ORDER:
        sib = tables[others[0]]
        before = ORDER.index(brand) < ORDER.index([b for b in ORDER if TITLES[b] == others[0]][0])
        return (sib["startIndex"] if before else sib["endIndex"]), None, None
    tall = next((el for el in elements if (image_height(d, el) or 0) > 200), None)
    if tall:
        return tall["startIndex"], (tall["startIndex"], tall["endIndex"]), None
    nxt = elements[0] if elements else vs_el
    return nxt["startIndex"] if elements else vs_el["endIndex"], None, None


# ---------- 上期人工項目 ----------

def prev_manual(old_grid, cur_label, prev_label, cfg):
    """先看文件裡的舊表（上週那張或這週重跑的），再看試算表（唯讀）。回傳 (上期, 本期既有值)。"""
    if old_grid and len(old_grid[0]) >= 3:
        col = {"this": 1, "prev": 2}
        by_name = {r[0]: r for r in old_grid[2:]}
        get = lambda c: {n: by_name[n][col[c]] for n in MANUAL if n in by_name and by_name[n][col[c]]}
        if old_grid[0][1] == cur_label:
            return get("prev"), get("this")
        if old_grid[0][1] == prev_label:
            return get("this"), {}
    try:
        from sheets_io import WEEKLY_SHEET, Sheets
        sh, tab, rows = Sheets(), "數據週報", row_numbers(cfg)
        tc, pc = cfg["this_col"], cfg["prev_col"]
        head = (sh.get(WEEKLY_SHEET, f"{tab}!{tc}{cfg['label_row']}") or [[""]])[0][0]
        col = pc if str(head).strip() == cur_label else tc if str(head).strip() == prev_label else None
        if col:
            vals = sh.get(WEEKLY_SHEET, f"{tab}!{col}{cfg['first_row']}:{col}{rows[ROWS[-1]]}")
            cell = lambda r: (vals[r - cfg["first_row"]] or [""])[0] if r - cfg["first_row"] < len(vals) else ""
            return {n: cell(rows[n]) for n in MANUAL if cell(rows[n]) != ""}, {}
    except Exception as e:
        print(f"⚠ 讀試算表上期人工項目失敗：{e}")
    return {}, {}


# ---------- 寫入 ----------

def rgb(h):
    return {"color": {"rgbColor": {k: int(h[i:i + 2], 16) / 255 for k, i in (("red", 1), ("green", 3), ("blue", 5))}}}


def write_table(s, doc_id, at, delete, grid, signs, colors):
    reqs = []
    if delete:
        reqs.append({"deleteContentRange": {"range": {"startIndex": delete[0], "endIndex": delete[1]}}})
    reqs.append({"insertTable": {"rows": len(grid), "columns": len(grid[0]), "location": {"index": at}}})
    post(s, doc_id, reqs)

    d = s.get(f"{DOCS}/{doc_id}").json()
    table = next(el for el in d["body"]["content"] if "table" in el and el["startIndex"] >= at)
    t0 = table["startIndex"]
    cells = [(r, c, cell["content"][0]["startIndex"])
             for r, row in enumerate(table["table"]["tableRows"]) for c, cell in enumerate(row["tableCells"])]
    post(s, doc_id, [{"insertText": {"location": {"index": i}, "text": grid[r][c]}}
                     for r, c, i in sorted(cells, key=lambda x: -x[2]) if grid[r][c]])

    d = s.get(f"{DOCS}/{doc_id}").json()
    table = next(el for el in d["body"]["content"] if el.get("startIndex") == t0)
    styles = [{"updateTableColumnProperties": {"tableStartLocation": {"index": t0}, "columnIndices": [i],
               "tableColumnProperties": {"widthType": "FIXED_WIDTH", "width": {"magnitude": w, "unit": "PT"}},
               "fields": "widthType,width"}} for i, w in enumerate(WIDTHS)]
    # 列高緊縮：上下內距 1pt，整張表高度和過去貼的試算表截圖差不多
    styles.append({"updateTableCellStyle": {
        "tableRange": {"tableCellLocation": {"tableStartLocation": {"index": t0}, "rowIndex": 0, "columnIndex": 0},
                       "rowSpan": len(grid), "columnSpan": len(grid[0])},
        "tableCellStyle": {k: {"magnitude": v, "unit": "PT"} for k, v in
                           (("paddingTop", 1), ("paddingBottom", 1), ("paddingLeft", 5), ("paddingRight", 5))},
        "fields": "paddingTop,paddingBottom,paddingLeft,paddingRight"}})
    for c in range(len(grid[0])):
        styles.append({"updateTableCellStyle": {
            "tableRange": {"tableCellLocation": {"tableStartLocation": {"index": t0}, "rowIndex": 0, "columnIndex": c},
                           "rowSpan": 1, "columnSpan": 1},
            "tableCellStyle": {"backgroundColor": rgb(colors[0] if c == 0 else colors[1])}, "fields": "backgroundColor"}})
    for r, row in enumerate(table["table"]["tableRows"]):
        for c, cell in enumerate(row["tableCells"]):
            p = cell["content"][0]
            rng = {"startIndex": p["startIndex"], "endIndex": p["endIndex"] - 1}
            styles.append({"updateParagraphStyle": {"range": {"startIndex": p["startIndex"], "endIndex": p["endIndex"]},
                           "paragraphStyle": {"alignment": "START" if c == 0 else "END", "lineSpacing": 100,
                                              "spaceAbove": {"magnitude": 0, "unit": "PT"},
                                              "spaceBelow": {"magnitude": 0, "unit": "PT"}},
                           "fields": "alignment,lineSpacing,spaceAbove,spaceBelow"}})
            if rng["endIndex"] <= rng["startIndex"]:
                continue
            ts, fields = {"fontSize": {"magnitude": 11, "unit": "PT"}, "bold": r < 2}, ["fontSize", "bold"]
            sign = signs.get((r, c), 0)
            if sign:
                ts["foregroundColor"] = rgb(GOOD if sign > 0 else BAD)
                fields.append("foregroundColor")
            styles.append({"updateTextStyle": {"range": rng, "textStyle": ts, "fields": ",".join(fields)}})
    post(s, doc_id, styles)


def post(s, doc_id, reqs):
    if not reqs:
        return
    r = s.post(f"{DOCS}/{doc_id}:batchUpdate", json={"requests": reqs})
    if not r.ok:
        raise SystemExit(f"寫入失敗：{r.status_code} {r.text[:500]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("brand", choices=list(TITLES))
    ap.add_argument("--week", required=True, help="報告週的週一（文件所屬週）YYYY-MM-DD")
    ap.add_argument("--month", help="月報品牌：YYYY-MM")
    ap.add_argument("--doc", required=True)
    ap.add_argument("--cwv")
    ap.add_argument("--links", type=int)
    ap.add_argument("--domains", type=int)
    ap.add_argument("--dr", type=float)
    ap.add_argument("--ur", type=float)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cfg = BRANDS[a.brand]
    monday = dt.date.fromisoformat(a.week)
    if (cfg["period"] == "month") != bool(a.month):
        ap.error(f"{a.brand} 是{'月報，請給 --month' if cfg['period'] == 'month' else '週報，不用 --month'}")
    (cs, ce), (ps, pe) = periods(cfg, a.week, a.month)
    cur_label, prev_label = label(cs, ce), label(ps, pe)
    s = AuthorizedSession(load_credentials(allow_browser=False, scopes=LOCAL_SCOPES))
    name = check_doc(s, a.doc, monday)

    cur = {**ga4_sheet_method(cfg["ga4"], cs.isoformat(), ce.isoformat()),
           **gsc_totals(cfg["site"], cfg["country"], cs.isoformat(), ce.isoformat())}
    prev = {**ga4_sheet_method(cfg["ga4"], ps.isoformat(), pe.isoformat()),
            **gsc_totals(cfg["site"], cfg["country"], ps.isoformat(), pe.isoformat())}
    (m1, m2), (p1, p2) = mtd_ranges(cfg, (cs, ce))
    cur["本月累積非付費流量"], miss1 = ga4_daily_sum(cfg["ga4"], m1, m2)
    prev["本月累積非付費流量"], miss2 = ga4_daily_sum(cfg["ga4"], p1, p2)
    warnings = [] if cfg.get("sparse") else [f"GA4 缺資料日期：{x}（稍後重跑）" for x in miss1 + miss2]

    d = s.get(f"{DOCS}/{a.doc}").json()
    at, delete, old = placement(d, a.brand)
    pm, existing = prev_manual(old, cur_label, prev_label, cfg)
    given = {"良好網站比例": a.cwv, "GSC外鏈數量": a.links, "GSC外鏈域名": a.domains, "DR": a.dr, "UR": a.ur}
    for n in MANUAL:
        cur[n] = given[n] if given[n] is not None else existing.get(n, "")
        prev[n] = pm.get(n, "")

    unit = "週" if cfg["period"] == "week" else "月"
    grid = [[TITLES[a.brand], cur_label, prev_label, "變化"], ["指標", f"本{unit}數據", f"上{unit}數據", "變化"]]
    signs = {}
    for i, n in enumerate(ROWS, start=2):
        txt, sign = change(n, cur.get(n), prev.get(n))
        grid.append([n, fmt(n, cur.get(n)), fmt(n, prev.get(n)), txt])
        signs[(i, 3)] = sign
    grid[1][3] = ""

    print(f"{a.brand} {cs}～{ce} vs {ps}～{pe}（GSC 國家：{cfg['country'] or '不篩'}）→ {name}")
    print(f"  位置：{'原地換新舊表' if old else '取代舊的試算表截圖' if delete else '接在同段落其他表格旁或 vs 段落後'}（index {at}）")
    print(f"  月累區間：{m1}～{m2} vs {p1}～{p2}")
    for row in grid:
        print("  " + " | ".join(row))
    pending = [n for n in MANUAL if cur[n] in ("", None)]
    if pending:
        print("  人工待填：", "、".join(pending))
    for w in warnings:
        print("WARNING", w)
    if given["GSC外鏈域名"] is not None and to_num(prev["GSC外鏈域名"]) not in (None, given["GSC外鏈域名"]):
        print(f"DOMAINS_CHANGED {a.brand} {int(to_num(prev['GSC外鏈域名']))} -> {given['GSC外鏈域名']}")

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"{cs}_{a.brand}_table.json").write_text(json.dumps(
        {"brand": a.brand, "cur_label": cur_label, "prev_label": prev_label, "this": cur, "prev": prev},
        ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if a.dry_run:
        print("dry-run，沒有寫入")
        return
    colors = COLORS.get(a.brand, DEFAULT_COLORS)
    write_table(s, a.doc, at, delete, grid, signs, colors)
    print(f"已寫入表格：https://docs.google.com/document/d/{a.doc}/edit")


if __name__ == "__main__":
    main()
