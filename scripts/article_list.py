"""每週「文章與數據列表」的「核心關鍵字追蹤」分頁更新（TW 每週、HK 月報週才做）。

  python scripts/article_list.py check TW [--json]      # 唯讀：現在的狀態、有沒有 #REF!、下方表對不對
  python scripts/article_list.py run TW [--dry-run]     # 每週更新：下方表貼上期值 → 插 1 欄 → 貼本期 7 欄
  python scripts/article_list.py repair TW [--dry-run]  # 本期已貼但有錯：重貼下方表 C 欄、重貼最新 7 欄，不插欄
  python scripts/article_list.py formulas TW [--dry-run]  # 把下方表 B、D 欄改成公式（=G3、=H3…）

共用參數：--sheet-id <試算表 ID>（預設是正式表）、--allow-original（要寫正式表才加）。

寫入保護：預設只能寫「標題以 [TEST] 開頭」的試算表；正式表 ID 要另外加 --allow-original 才放行，
其他試算表一律拒絕。check 和 --dry-run 只讀不寫。

分頁結構（列號、欄號都是執行時偵測，不寫死）：
  G:M      公式區，G1 是本期週次（=Welly!$A2），第 2 列是 7 個欄名，第 3 列起是關鍵字
  最右邊    歷史區每期只留 1 欄大字排名，最後一期是完整 7 欄
  下方表    A 欄有「目標關鍵字」的那一列是標題列；B 本期大字、C 上期大字、D 本期頁面、E 上期頁面

#REF! 的來源：GSCdata 有全形或大小寫變體的重複關鍵字時，G 欄的 filter 會回多列。
本程式只會指出是哪一列，不刪 GSCdata 的任何資料，請人到 GSCdata 處理後再跑。
"""

import argparse
import datetime as dt
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession

from welly_auth import LOCAL_SCOPES, load_credentials

API = "https://sheets.googleapis.com/v4/spreadsheets"
ORIGINALS = {
    "TW": "1WdYv__K7nbBPl-Tr0AHedZnvK-3Ws8ljUB-VgedbYGg",   # 1-Welly文章與數據列表
    "HK": "1rLO_nUSzUz7bMA5iLl_y3oADhv5iDr8fqEcI8uLg5RM",   # HK Welly 文章與數據列表
}
TEST_PREFIX = "[TEST]"
TAB, GSC_TAB = "核心關鍵字追蹤", "GSCdata"
BLOCK = ["大字排名", "頁面排名", "標題點擊率", "文章狀況", "停留時間", "跳出率", "停留時間原數據"]
AUTO_NOTE = "數據自動化區"
LOWER_MARK = "目標關鍵字"
G, M = 7, 13                 # 公式區的欄號（從 1 算）
MIN_GSC_ROWS = 200           # GSCdata 少於這個列數視為資料沒匯好
MIN_RANK_RATIO = 0.3         # G 欄有數字的比例低於這個值也視為資料沒匯好
RESID = 30                   # 下方表底下多讀幾列，用來找貼歪留下的殘值
DRAFTS = Path(__file__).resolve().parent.parent / "drafts"
LABEL = {"ok": "OK  ", "info": "資訊", "bad": "問題"}


# ---------- 小工具 ----------

def col(n: int) -> str:
    """欄號（從 1 算）轉欄字母。"""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def cell(rows, r, c):
    """rows[r][c]，超出範圍回空字串（API 會省略尾端的空格）。"""
    return rows[r][c] if 0 <= r < len(rows) and 0 <= c < len(rows[r]) else ""


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def err_code(v):
    """錯誤值只留代碼，例如「#N/A (No matches…)」回「#N/A」；不是錯誤回 None。"""
    m = re.match(r"#[A-Z0-9/!?]+", v) if isinstance(v, str) else None
    return m.group(0) if m else None


def same(a, b):
    a, b = ("" if a is None else a), ("" if b is None else b)
    if is_num(a) and is_num(b):
        return abs(a - b) <= 1e-9 * max(1, abs(a), abs(b))
    if err_code(a) and err_code(b):
        return err_code(a) == err_code(b)
    return a == b


def diff_rows(xs, ys, first_row):
    """兩串值逐列比，回不一樣的列號。"""
    return [first_row + i for i, (x, y) in enumerate(zip(xs, ys)) if not same(x, y)]


def norm_week(s):
    """週次字串正規化：歷史標題有「10/26~11/01」「10-26-11-01」等寫法，只留數字比對。"""
    nums = re.findall(r"\d+", str(s))
    return tuple(int(n) for n in nums) if nums else re.sub(r"[\s~/\-]", "", str(s))


def norm_kw(s):
    """Sheets 的等號比對不分大小寫與全半形，這裡用 NFKC 加小寫模擬。"""
    return unicodedata.normalize("NFKC", str(s)).lower()


def loose_kw(s):
    return re.sub(r"\s+", "", norm_kw(s))


def rows_text(rows, limit=12):
    rows = list(rows)
    return "、".join(str(r) for r in rows[:limit]) + (f"…等 {len(rows)} 列" if len(rows) > limit else "")


# ---------- 試算表存取 ----------

class Book:
    def __init__(self, brand, sid, allow_original=False):
        self.brand, self.sid, self.allow_original = brand, sid, allow_original
        self.s = AuthorizedSession(load_credentials(allow_browser=False, scopes=LOCAL_SCOPES))

    def _get(self, url, params):
        """讀取；遇到每分鐘讀取上限（HTTP 429）就等一下再試。"""
        for wait in (0, 20, 40, 60):
            time.sleep(wait)
            r = self.s.get(url, params=params)
            if r.status_code != 429:
                break
        r.raise_for_status()
        return r.json()

    def meta(self):
        return self._get(f"{API}/{self.sid}", {"fields": "properties.title,sheets(properties,conditionalFormats)"})

    def values(self, ranges, formulas=False):
        j = self._get(f"{API}/{self.sid}/values:batchGet", {
            "ranges": ranges, "valueRenderOption": "FORMULA" if formulas else "UNFORMATTED_VALUE"})
        return [x.get("values", []) for x in j["valueRanges"]]

    def guard(self):
        """寫入前的白名單檢查：每次都重新讀標題，不用快取。"""
        title = self.meta()["properties"]["title"]
        if self.sid in ORIGINALS.values():
            if not self.allow_original:
                sys.exit(f"拒絕寫入：「{title}」是正式表。要寫正式表請加 --allow-original；測試請用 --sheet-id 指定 {TEST_PREFIX} 開頭的副本。")
        elif not title.startswith(TEST_PREFIX):
            sys.exit(f"拒絕寫入：「{title}」不是正式表，標題也不是 {TEST_PREFIX} 開頭。")

    def write(self, requests):
        """所有寫入都走這裡：一個 batchUpdate，其中一步失敗就整批不生效。"""
        self.guard()
        r = self.s.post(f"{API}/{self.sid}:batchUpdate", json={"requests": requests})
        if not r.ok:
            sys.exit(f"寫入失敗（整批都沒有生效）：HTTP {r.status_code} {r.text[:500]}")
        return r.json()


# ---------- 讀取現況 ----------

def load(book):
    """讀「核心關鍵字追蹤」和 GSCdata，回傳 st（狀態字典）。結構不對時 st['fatal'] 會有原因。"""
    meta = book.meta()
    st = {"brand": book.brand, "sheet_id": book.sid, "title": meta["properties"]["title"], "fatal": []}
    tabs = {s["properties"]["title"]: s for s in meta["sheets"]}
    if TAB not in tabs or GSC_TAB not in tabs:
        st["fatal"].append(f"找不到分頁「{TAB}」或「{GSC_TAB}」")
        return st
    st["tab_id"] = tabs[TAB]["properties"]["sheetId"]
    st["grid_cols"] = tabs[TAB]["properties"]["gridProperties"]["columnCount"]
    st["cf"] = [[(r.get("startColumnIndex", 0), r.get("endColumnIndex")) for r in rule["ranges"]]
                for rule in tabs[TAB].get("conditionalFormats", [])]

    head, col_a = book.values([f"{TAB}!1:2", f"{TAB}!A:A"])
    row1, row2 = (head + [[], []])[:2]
    col_a = [str(r[0]).strip() if r else "" for r in col_a]
    st["row1"], st["row2"] = row1, row2

    # 公式區與最右邊 7 欄的欄名
    if row2[G - 1:M] != BLOCK:
        st["fatal"].append(f"G2:M2 不是預期的 7 個欄名（讀到 {row2[G - 1:M]}）")
    if len(row2) < M + 8 or row2[-7:] != BLOCK:
        st["fatal"].append(f"最右邊 7 欄的第 2 列不是預期的 7 個欄名（讀到 {row2[-7:]}）")
    # 上方關鍵字列與下方表
    hdr = next((i for i, v in enumerate(col_a, 1) if v == LOWER_MARK), None)
    if not hdr:
        st["fatal"].append(f"A 欄找不到「{LOWER_MARK}」標題列")
    if st["fatal"]:
        return st
    top_end = 2
    while top_end < len(col_a) and col_a[top_end]:
        top_end += 1                     # 第 3 列起連續有關鍵字的最後一列
    low_end = hdr
    while low_end < len(col_a) and col_a[low_end]:
        low_end += 1
    if top_end < 3 or top_end >= hdr or low_end == hdr:
        st["fatal"].append(f"關鍵字列的範圍不合理（上方到第 {top_end} 列、標題列 {hdr}、下方到第 {low_end} 列）")
        return st
    last = len(row2) - 6                 # 最後一期大字排名欄（從 1 算）
    st.update(hdr=hdr, top_end=top_end, low_end=low_end, last=last, n_top=top_end - 2, n_low=low_end - hdr,
              top_kw=col_a[2:top_end], low_kw=col_a[hdr:low_end],
              last_title=str(cell([row1], 0, last - 1)), prev_title=str(cell([row1], 0, last - 2)),
              prev_is_rank=cell([row2], 0, last - 2) == BLOCK[0], note_left=str(cell([row1], 0, last)))

    low_rng = f"{TAB}!A{hdr - 2}:E{low_end + RESID}"
    gm, hist, low, gsc = book.values([f"{TAB}!G1:M{top_end}", f"{TAB}!{col(last - 1)}1:{col(last + 6)}{top_end}",
                                      low_rng, f"{GSC_TAB}!A:G"])
    low_f, g1_f, top_url = book.values([low_rng, f"{TAB}!G1", f"{TAB}!B3:B{top_end}"], formulas=True)
    st.update(gm=gm, hist=hist, low=low, low_f=low_f, low_first=hdr - 2, gsc=gsc,
              week=str(cell(gm, 0, 0)), g1_formula=str(cell(g1_f, 0, 0)), note_h1=str(cell(gm, 0, 1)),
              top_url=[str(r[0]).strip() if r else "" for r in top_url])
    return st


def low_col(st, c, rows=None, offset=0, formulas=False):
    """下方表某一欄（c：A=0…E=4）的資料列值；offset 用來試「貼歪幾列」。"""
    src = st["low_f"] if formulas else st["low"]
    base = st["hdr"] + 1 - st["low_first"] + offset
    return [cell(src, base + i, c) for i in range(rows or st["n_low"])]


def hist_col(st, k):
    """最右邊區域的資料列值；k=0 是最後一期的前一欄，k=1 是最後一期大字，k=2 是它右邊的頁面排名…"""
    return [cell(st["hist"], 2 + i, k) for i in range(st["n_top"])]


def gm_col(st, k):
    return [cell(st["gm"], 2 + i, k) for i in range(st["n_top"])]


def done_already(st):
    return bool(st["week"]) and norm_week(st["week"]) == norm_week(st["last_title"])


# ---------- 各項檢查 ----------

def ref_errors(st):
    """G:M 有 #REF! 的列：[(列號, 關鍵字, [欄字母…])]"""
    out = []
    for i in range(st["n_top"]):
        cols = [col(G + k) for k in range(7) if err_code(cell(st["gm"], 2 + i, k)) == "#REF!"]
        if cols:
            out.append((3 + i, st["top_kw"][i], cols))
    return out


def gsc_duplicates(st):
    """GSCdata 裡同一組（query 正規化後, page）出現多列，而且剛好對到追蹤關鍵字的，就是 #REF! 的來源。"""
    tracked = {(norm_kw(k), norm_kw(u)): 3 + i for i, (k, u) in enumerate(zip(st["top_kw"], st["top_url"]))}
    groups = {}
    for r, row in enumerate(st["gsc"][1:], 2):
        key = (norm_kw(cell([row], 0, 0)).strip(), norm_kw(cell([row], 0, 1)).strip())
        if key in tracked:
            groups.setdefault(key, []).append(r)
    out = []
    for key, rows in groups.items():
        if len(rows) < 2:
            continue
        top_row = tracked[key]
        kw = st["top_kw"][top_row - 3]
        info = [{"row": r, "query": str(st["gsc"][r - 1][0]), "page": str(cell(st["gsc"], r - 1, 1)),
                 "impressions": cell(st["gsc"], r - 1, 4)} for r in rows]
        # 保留寫法和關鍵字一樣（只差大小寫）的那列；都不是或有多列時留曝光最高的
        plain = [x for x in info if x["query"].strip().lower() == kw.lower()]
        keep = max(plain or info, key=lambda x: x["impressions"] if is_num(x["impressions"]) else 0)
        for x in info:
            x["suggest_delete"] = x is not keep
        out.append({"top_row": top_row, "keyword": kw, "rows": info})
    return sorted(out, key=lambda x: x["top_row"])


def alignment(st):
    """下方表的關鍵字是不是和上方第 3 列起逐列對應。寫法略有不同（大小寫、空白、多了「是什麼」）算對得上，另外列出。"""
    res = {"ok": st["n_top"] == st["n_low"], "loose": [], "mismatch": []}
    for i, (a, b) in enumerate(zip(st["top_kw"], st["low_kw"])):
        if a == b:
            continue
        la, lb = loose_kw(a), loose_kw(b)
        item = {"top_row": 3 + i, "top": a, "low_row": st["hdr"] + 1 + i, "low": b}
        if la == lb or (la and lb and (la in lb or lb in la)):
            res["loose"].append(item)
        else:
            res["mismatch"].append(item)
    res["ok"] = res["ok"] and not res["mismatch"]
    return res


def find_shift(st, c, expected):
    """下方表某欄和應有值對不上時，試試是不是整段貼歪了幾列。回傳位移（往下為正）或 None。"""
    for k in (-2, -1, 1, 2, 3, 4, 5):
        if not diff_rows(low_col(st, c, offset=k), expected, 0):
            return k
    return None


def residue(st, c):
    """下方表底下（A 欄空白的列）某欄殘留的值：回列號清單。"""
    base = st["low_end"] + 1 - st["low_first"]
    return [st["low_end"] + 1 + i for i in range(RESID) if cell(st["low"], base + i, c) != ""]


def find_run_backup(st):
    """找 run 留下的備份（同一份試算表、同一期），裡面有被蓋掉的上一期頁面排名。"""
    for p in sorted(DRAFTS.glob(f"article_list_backup_{st['brand']}_*.json"), reverse=True):
        try:
            b = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if b.get("kind") == "run" and b.get("sheet_id") == st["sheet_id"] \
                and norm_week(b.get("week", "")) == norm_week(st["week"]) and len(b.get("prev_page", [])) == st["n_top"]:
            return p, b
    return None, None


def formula_state(st):
    """下方表 B、D 欄有幾列是預期的公式（=G3、=H3…）。"""
    out = {}
    for name, c, src in (("B", 1, "G"), ("D", 3, "H")):
        f = low_col(st, c, formulas=True)
        good = sum(1 for i, x in enumerate(f) if str(x).replace("$", "").upper() == f"={src}{3 + i}")
        out[name] = {"expected": good, "other_formula": sum(1 for x in f if str(x).startswith("=")) - good,
                     "fixed_value": sum(1 for x in f if not str(x).startswith("="))}
    return out


def inspect(st):
    """跑完所有檢查，回傳 (結果字典, 訊息清單)。訊息是 (等級, 文字)，等級：ok、info、bad。"""
    msgs, res = [], {"brand": st["brand"], "sheet_id": st["sheet_id"], "title": st["title"]}
    if st["fatal"]:
        res["fatal"] = st["fatal"]
        return res, [("bad", x) for x in st["fatal"]]
    last, hdr = st["last"], st["hdr"]
    done = done_already(st)
    res.update(week=st["week"], last_col=col(last), last_title=st["last_title"], prev_col=col(last - 1),
               prev_title=st["prev_title"], already_done=done, top_rows=[3, st["top_end"]],
               lower_header_row=hdr, lower_rows=[hdr + 1, st["low_end"]], gsc_rows=max(len(st["gsc"]) - 1, 0))
    msgs.append(("info", f"本期週次（G1）：{st['week'] or '（空白）'}"))
    msgs.append(("info", f"關鍵字 {st['n_top']} 個（第 3 到 {st['top_end']} 列）；下方表標題在第 {hdr} 列，資料第 {hdr + 1} 到 {st['low_end']} 列"))
    msgs.append(("info", f"最後一個週次欄：{col(last)} 欄「{st['last_title']}」，它右邊 6 欄（{col(last + 1)}:{col(last + 6)}）是同一期的其他數據；前一期是 {col(last - 1)} 欄「{st['prev_title']}」"))
    if not st["week"]:
        msgs.append(("bad", "G1 是空白，不知道本期是哪一週"))
    elif done:
        msgs.append(("info", "本期已經貼過了（G1 和最後週次欄的標題相同），再跑 run 會略過"))
    else:
        msgs.append(("info", "本期還沒貼（G1 和最後週次欄的標題不同），可以跑 run"))
    if st["note_h1"] != AUTO_NOTE:
        msgs.append(("info", f"H1 不是「{AUTO_NOTE}」（讀到「{st['note_h1']}」），不影響執行"))
    if st["note_left"]:
        msgs.append(("bad", f"{col(last + 1)}1 殘留「{st['note_left']}」（貼上時多帶的），repair 會清掉"))
    res["note_left"] = st["note_left"]

    # GSCdata 與 #REF!
    ranked = sum(1 for v in gm_col(st, 0) if is_num(v))
    res["rank_filled"] = ranked
    if res["gsc_rows"] < MIN_GSC_ROWS or ranked < st["n_top"] * MIN_RANK_RATIO:
        msgs.append(("bad", f"GSCdata 只有 {res['gsc_rows']} 列、G 欄只有 {ranked}/{st['n_top']} 列有排名，資料可能還沒匯好"))
        res["gsc_ok"] = False
    else:
        msgs.append(("ok", f"GSCdata 有 {res['gsc_rows']} 列資料，G 欄 {ranked}/{st['n_top']} 列有排名（其餘是 #N/A，代表該關鍵字這期沒有資料，屬正常）"))
        res["gsc_ok"] = True
    refs, dups = ref_errors(st), gsc_duplicates(st)
    res["ref_errors"] = [{"row": r, "keyword": k, "cols": c} for r, k, c in refs]
    res["gsc_duplicates"] = dups
    dup_by_row = {d["top_row"]: d for d in dups}
    if not refs and not dups:
        msgs.append(("ok", "G:M 沒有 #REF!，GSCdata 也沒有會造成 #REF! 的重複關鍵字"))
    for r, kw, cols in refs:
        msgs.append(("bad", f"第 {r} 列「{kw}」的 {'、'.join(cols)} 欄是 #REF!"))
        if r not in dup_by_row:
            msgs.append(("bad", "  在 GSCdata 找不到重複列，請人工看這一格的錯誤說明"))
    for d in dups:
        if not any(r == d["top_row"] for r, _, _ in refs):
            msgs.append(("bad", f"GSCdata 有重複關鍵字，對到第 {d['top_row']} 列「{d['keyword']}」（G 欄目前沒顯示 #REF!，但建議一併處理）"))
        for x in d["rows"]:
            act = "建議刪除這一列" if x["suggest_delete"] else "保留"
            msgs.append(("bad" if x["suggest_delete"] else "info",
                         f"  GSCdata 第 {x['row']} 列：query「{x['query']}」、page {x['page']}、曝光 {x['impressions']} → {act}"))

    # 最新 7 欄和現在的 G:M 是否一致（本期已貼才有意義）
    if done:
        bad_cells = latest_block_diff(st)
        res["latest_block_diff"] = len(bad_cells)
        refs_in_hist = sum(1 for i in range(st["n_top"]) for k in range(1, 8) if err_code(cell(st["hist"], 2 + i, k)) == "#REF!")
        res["latest_block_ref"] = refs_in_hist
        if bad_cells or refs_in_hist:
            where = f"：{'、'.join(bad_cells[:8])}{'…' if len(bad_cells) > 8 else ''}" if bad_cells else ""
            msgs.append(("bad", f"最新 7 欄（{col(last)}:{col(last + 6)}）裡有 {refs_in_hist} 格 #REF! 被貼進歷史區，和現在的 G:M 有 {len(bad_cells)} 格不同{where}"))
        else:
            msgs.append(("ok", f"最新 7 欄（{col(last)}:{col(last + 6)}）和現在的 G:M 逐格相同"))

    # 上下表關鍵字對應
    al = alignment(st)
    res["alignment"] = al
    if al["ok"]:
        msgs.append(("ok", f"下方表 {st['n_low']} 列和上方關鍵字逐列對應" + (f"（其中 {len(al['loose'])} 列寫法略有不同，位置相同）" if al["loose"] else "")))
        for x in al["loose"]:
            msgs.append(("info", f"  第 {x['top_row']} 列「{x['top']}」↔ 第 {x['low_row']} 列「{x['low']}」"))
    else:
        msgs.append(("bad", f"下方表和上方關鍵字對不起來：上方 {st['n_top']} 列、下方 {st['n_low']} 列"))
        for x in al["mismatch"][:10]:
            msgs.append(("bad", f"  第 {x['top_row']} 列「{x['top']}」↔ 第 {x['low_row']} 列「{x['low']}」"))

    # 下方表 C 欄（上期大字排名）
    c_head, e_head = str(cell(st["low"], hdr - st["low_first"], 2)), str(cell(st["low"], hdr - st["low_first"], 4))
    res["lower_c_header"], res["lower_e_header"] = c_head, e_head
    if al["ok"] and st["prev_is_rank"]:
        exp_c = hist_col(st, 0)
        bad = diff_rows(low_col(st, 2), exp_c, hdr + 1)
        head_ok = norm_week(c_head) == norm_week(st["prev_title"])
        res["lower_c"] = {"compared_with": col(last - 1), "diff_rows": bad, "header_ok": head_ok}
        tail = "" if done else "（本期還沒貼，run 的時候會換成最後週次欄的值）"
        if not bad and head_ok:
            msgs.append(("ok", f"下方表 C 欄和 {col(last - 1)} 欄「{st['prev_title']}」逐列一致{tail}"))
        else:
            shift = find_shift(st, 2, exp_c) if bad else None
            res["lower_c"]["shift"] = shift
            if shift:
                msgs.append(("bad", f"下方表 C 欄貼歪了：整段往{'下' if shift > 0 else '上'}偏 {abs(shift)} 列（值在 C{hdr + 1 + shift}:C{st['low_end'] + shift}，應該在 C{hdr + 1}:C{st['low_end']}）"))
            elif bad:
                msgs.append(("bad", f"下方表 C 欄有 {len(bad)} 列和 {col(last - 1)} 欄「{st['prev_title']}」不同：第 {rows_text(bad)} 列{tail}"))
            if not head_ok:
                msgs.append(("bad", f"下方表 C 欄標題是「{c_head}」，應該是「{st['prev_title']}」"))
    for name, c in (("C", 2), ("E", 4)):
        left = residue(st, c)
        res[f"residue_{name}"] = left
        if left:
            msgs.append(("bad", f"下方表底下 {name} 欄有殘值：第 {rows_text(left)} 列"))

    # 下方表 E 欄（上期頁面排名）
    path, backup = find_run_backup(st) if done else (None, None)
    e_now, d_now = low_col(st, 4), low_col(st, 3)
    fs = formula_state(st)
    if backup:
        bad = diff_rows(e_now, backup["prev_page"], hdr + 1)
        res["lower_e"] = {"source": path.name, "diff_rows": bad}
        msgs.append(("ok", f"下方表 E 欄和備份裡的上一期頁面排名逐列一致（{path.name}）") if not bad else
                    ("bad", f"下方表 E 欄有 {len(bad)} 列和備份裡的上一期頁面排名不同：第 {rows_text(bad)} 列"))
    elif done:
        res["lower_e"] = {"source": None}
        hint = "E 欄和 D 欄（寫死的舊值）逐列相同，看起來就是上一期的頁面排名" if fs["D"]["fixed_value"] == st["n_low"] and not diff_rows(e_now, d_now, 0) else "無從比對"
        msgs.append(("info", f"下方表 E 欄：上一期的頁面排名在歷史區已經被本期蓋掉，也沒有 run 的備份可比。{hint}"))
    else:
        res["lower_e"] = {"source": None}
        msgs.append(("info", f"下方表 E 欄：run 的時候會換成 {col(last + 1)} 欄（「{st['last_title']}」的頁面排名）"))

    # 下方表 B、D 欄是不是公式
    res["lower_formulas"] = fs
    for name, src in (("B", "G"), ("D", "H")):
        f = fs[name]
        if f["expected"] == st["n_low"]:
            msgs.append(("ok", f"下方表 {name} 欄 {st['n_low']} 列都是公式（={src}3 這種寫法），會自動跟著本期更新"))
        else:
            msgs.append(("bad", f"下方表 {name} 欄不是公式：{f['fixed_value']} 列是寫死的值、{f['other_formula']} 列是其他公式（可用 formulas 改成 ={src}3 這種寫法）"))
    a_formula = sum(1 for x in low_col(st, 0, formulas=True) if str(x).startswith("="))
    res["lower_a_formulas"] = a_formula
    res["problems"] = sum(1 for lv, _ in msgs if lv == "bad")
    return res, msgs


def latest_block_diff(st):
    """最新 7 欄和 G:M 不同的儲存格（用歷史區的位址表示）。第 1 列第 2 欄應該是空白。"""
    out = []
    for r in range(st["top_end"]):
        for k in range(7):
            want = "" if (r, k) == (0, 1) else cell(st["gm"], r, k)
            if not same(cell(st["hist"], r, k + 1), want):
                out.append(f"{col(st['last'] + k)}{r + 1}")
    return out


def show(msgs):
    for level, text in msgs:
        print(f"[{LABEL[level]}] {text}")


# ---------- batchUpdate 的零件 ----------

def grid(st, r1, r2, c1, c2):
    """列號、欄號都從 1 算，含頭含尾。"""
    return {"sheetId": st["tab_id"], "startRowIndex": r1 - 1, "endRowIndex": r2, "startColumnIndex": c1 - 1, "endColumnIndex": c2}


def paste_values(st, src, dst):
    return {"copyPaste": {"source": grid(st, *src), "destination": grid(st, *dst), "pasteType": "PASTE_VALUES"}}


def clear_values(st, r1, r2, c1, c2):
    return {"updateCells": {"range": grid(st, r1, r2, c1, c2), "fields": "userEnteredValue"}}


def to_cell(v):
    if v == "" or v is None:
        return {}
    if isinstance(v, bool):
        return {"userEnteredValue": {"boolValue": v}}
    if is_num(v):
        return {"userEnteredValue": {"numberValue": v}}
    if str(v).startswith("="):
        return {"userEnteredValue": {"formulaValue": v}}
    if err_code(v) == "#N/A":
        return {"userEnteredValue": {"formulaValue": "=NA()"}}
    return {"userEnteredValue": {"stringValue": str(v)}}


def write_column(st, r1, c, values):
    return {"updateCells": {"range": grid(st, r1, r1 + len(values) - 1, c, c), "fields": "userEnteredValue",
                            "rows": [{"values": [to_cell(v)]} for v in values]}}


def save_backup(st, kind, extra):
    DRAFTS.mkdir(exist_ok=True)
    path = DRAFTS / f"article_list_backup_{st['brand']}_{dt.datetime.now():%Y%m%d_%H%M%S}.json"
    data = {"kind": kind, "brand": st["brand"], "sheet_id": st["sheet_id"], "title": st["title"],
            "saved_at": dt.datetime.now().isoformat(timespec="seconds"), "week": st["week"],
            "last_col": col(st["last"]), "last_title": st["last_title"], "prev_title": st["prev_title"],
            "lower_first_row": st["low_first"], "lower_values": st["low"], "lower_formulas": st["low_f"],
            "latest_block_first_col": col(st["last"] - 1), "latest_block_values": st["hist"], **extra}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已備份會被覆蓋的原值：{path}")
    return path


def unchanged_or_exit(book, st):
    """寫入前重讀第 1、2 列和 A 欄，和剛才分析時不同就停（代表有人同時在改）。"""
    head, col_a = book.values([f"{TAB}!1:2", f"{TAB}!A:A"])
    row1, row2 = (head + [[], []])[:2]
    col_a = [str(r[0]).strip() if r else "" for r in col_a]
    if row1 != st["row1"] or row2 != st["row2"] or col_a[2:st["top_end"]] != st["top_kw"] or col_a[st["hdr"] - 1:st["low_end"]] != [LOWER_MARK] + st["low_kw"]:
        sys.exit("停止：分析之後試算表的第 1、2 列或 A 欄被改過了，沒有寫入。請重跑一次。")


def stop_if_fatal(st):
    if st["fatal"]:
        show([("bad", x) for x in st["fatal"]])
        sys.exit("停止：分頁結構和預期不同，沒有寫入。")


def report(checks):
    """印讀回驗證的結果，回傳是否全過。checks = [(是否通過, 說明)]"""
    for ok, text in checks:
        print(f"[{'通過' if ok else '不符'}] {text}")
    return all(ok for ok, _ in checks)


# ---------- 子命令 ----------

def cmd_check(book, a):
    st = load(book)
    res, msgs = inspect(st)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"== {st['brand']}「{st['title']}」檢查結果 ==")
        show(msgs)
        n = sum(1 for lv, _ in msgs if lv == "bad")
        print(f"\n結論：{'沒有問題' if not n else f'有 {n} 項要處理（上面標「問題」的）'}")
    sys.exit(1 if any(lv == "bad" for lv, _ in msgs) else 0)


def cmd_run(book, a):
    st = load(book)
    stop_if_fatal(st)
    last, hdr, top_end, n = st["last"], st["hdr"], st["top_end"], st["n_top"]
    print(f"== {st['brand']}「{st['title']}」每週更新 ==")
    print(f"本期（G1）：{st['week']}｜最後週次欄：{col(last)}「{st['last_title']}」")
    if done_already(st):
        print("本期已經貼過了（G1 和最後週次欄的標題相同），略過，沒有寫入。要修正已貼的內容請用 repair。")
        return
    # 前置檢查
    stops = []
    if not st["week"] or len(norm_week(st["week"])) < 2:
        stops.append(f"G1 的週次看不懂（讀到「{st['week']}」）")
    refs, dups = ref_errors(st), {d["top_row"]: d for d in gsc_duplicates(st)}
    for r, kw, cols in refs:
        stops.append(f"第 {r} 列「{kw}」的 {'、'.join(cols)} 欄是 #REF!")
        for x in dups.get(r, {}).get("rows", []):
            stops.append(f"  GSCdata 第 {x['row']} 列：query「{x['query']}」、page {x['page']} → {'建議刪除這一列' if x['suggest_delete'] else '保留'}")
    gsc_rows, ranked = max(len(st["gsc"]) - 1, 0), sum(1 for v in gm_col(st, 0) if is_num(v))
    if gsc_rows < MIN_GSC_ROWS or ranked < n * MIN_RANK_RATIO:
        stops.append(f"GSCdata 只有 {gsc_rows} 列、G 欄只有 {ranked}/{n} 列有排名，資料可能還沒匯好")
    al = alignment(st)
    if not al["ok"]:
        stops.append(f"下方表和上方關鍵字對不起來（上方 {n} 列、下方 {st['n_low']} 列，不同的有 {len(al['mismatch'])} 列），請先用 check 看細節")
    if stops:
        show([("bad", x) for x in stops])
        print("\n沒有寫入。" + ("請到 GSCdata 處理上面列出的重複列（刪掉建議刪除的那一列）後再跑一次。" if refs else "請處理上面的問題後再跑一次。"))
        sys.exit(1)

    e_head_formula = str(cell(st["low_f"], hdr - st["low_first"], 4)).startswith("=")
    print("前置檢查通過。要做的事（一次寫入，依序）：")
    print(f"  1. 下方表 C{hdr + 1}:C{st['low_end']} ← {col(last)}3:{col(last)}{top_end} 的值（「{st['last_title']}」大字排名），C{hdr} 標題改成「{st['last_title']}」")
    print(f"  2. 下方表 E{hdr + 1}:E{st['low_end']} ← {col(last + 1)}3:{col(last + 1)}{top_end} 的值（「{st['last_title']}」頁面排名）" +
          (f"，E{hdr} 是公式不動" if e_head_formula else f"，E{hdr} 標題改成「{st['last_title']}」"))
    print(f"  3. 在 {col(last + 1)} 欄左邊插 1 欄（原本的 {col(last + 1)}:{col(last + 6)} 往右移成 {col(last + 2)}:{col(last + 7)}）")
    print(f"  4. G1:M{top_end} 貼成值到 {col(last + 1)}1:{col(last + 7)}{top_end}（新欄＝「{st['week']}」大字排名，後 6 欄蓋掉「{st['last_title']}」的 6 欄）")
    print(f"  5. 清掉 {col(last + 2)}1 多帶的「{AUTO_NOTE}」")
    if a.dry_run:
        print(f"\n--dry-run：以上都沒有執行。正式執行時會先備份到 {DRAFTS}\\article_list_backup_{st['brand']}_<時間>.json")
        return
    book.guard()
    save_backup(st, "run", {"prev_rank": hist_col(st, 1), "prev_page": hist_col(st, 2)})
    unchanged_or_exit(book, st)
    reqs = [paste_values(st, (3, top_end, last, last), (hdr + 1, st["low_end"], 3, 3)),
            paste_values(st, (3, top_end, last + 1, last + 1), (hdr + 1, st["low_end"], 5, 5)),
            paste_values(st, (1, 1, last, last), (hdr, hdr, 3, 3))]
    if not e_head_formula:
        reqs.append(paste_values(st, (1, 1, last, last), (hdr, hdr, 5, 5)))
    reqs += [{"insertDimension": {"range": {"sheetId": st["tab_id"], "dimension": "COLUMNS", "startIndex": last, "endIndex": last + 1},
                                  "inheritFromBefore": True}},
             paste_values(st, (1, top_end, G, M), (1, top_end, last + 1, last + 7)),
             clear_values(st, 1, 1, last + 2, last + 2)]
    book.write(reqs)
    print("已寫入，讀回驗證：")

    new = load(book)
    stop_if_fatal(new)
    checks = [
        (new["grid_cols"] == st["grid_cols"] + 1 and new["last"] == last + 1, f"欄數加 1：{st['grid_cols']} → {new['grid_cols']}，最後週次欄從 {col(last)} 變成 {col(new['last'])}"),
        (new["last_title"] == new["week"] == st["week"], f"新欄 {col(new['last'])}1 的標題＝G1：「{new['last_title']}」"),
        (new["prev_title"] == st["last_title"] and not diff_rows(hist_col(new, 0), hist_col(st, 1), 3),
         f"上一期「{st['last_title']}」的大字排名留在 {col(last)} 欄，{n} 列的值都沒變"),
    ]
    bad = diff_rows(hist_col(new, 1), gm_col(new, 0), 3)
    checks.append((not bad, f"新欄 {col(new['last'])} 的數值＝G 欄：{n - len(bad)}/{n} 列相同"))
    cells = latest_block_diff(new)
    total = top_end * 7
    checks.append((not cells, f"新 7 欄 {col(new['last'])}:{col(new['last'] + 6)} 和 G:M 逐格相同：{total - len(cells)}/{total} 格（含第 1、2 列，{col(new['last'] + 1)}1 已清空）"))
    old6 = [same(cell(new["hist"], r, k), cell(st["hist"], r, k)) for r in range(2, top_end) for k in range(2, 8)]
    checks.append((True, f"被蓋掉的是上一期的 6 欄：原 {col(last + 1)}:{col(last + 6)} 的 {len(old6)} 格裡有 {old6.count(False)} 格換成本期的值（其餘兩期數值相同），原值在備份檔"))
    bad_c, bad_e = diff_rows(low_col(new, 2), hist_col(st, 1), hdr + 1), diff_rows(low_col(new, 4), hist_col(st, 2), hdr + 1)
    c_head, e_head = str(cell(new["low"], hdr - new["low_first"], 2)), str(cell(new["low"], hdr - new["low_first"], 4))
    checks.append((not bad_c and c_head == st["last_title"], f"下方表 C 欄＝上一期大字排名：{n - len(bad_c)}/{n} 列相同，標題「{c_head}」"))
    checks.append((not bad_e and e_head == st["last_title"], f"下方表 E 欄＝上一期頁面排名：{n - len(bad_e)}/{n} 列相同，標題「{e_head}」"))
    grew = [(i, o, w) for i, (olds, news) in enumerate(zip(st["cf"], new["cf"])) for o, w in zip(olds, news) if o != w]
    edge = sum(1 for rule in st["cf"] for s, e in rule if e is not None and s <= last < e)
    checks.append((len(grew) == edge, f"條件格式：涵蓋插入位置的 {edge} 個範圍有 {len(grew)} 個跟著延伸" +
                   "".join(f"（規則 {i + 1}：{col(o[0] + 1)}:{col(o[1])} → {col(w[0] + 1)}:{col(w[1])}）" for i, o, w in grew)))
    ok = report(checks)
    print("\n完成。" if ok else "\n有項目不符，請對照備份檔檢查。")
    sys.exit(0 if ok else 1)


def cmd_repair(book, a):
    st = load(book)
    stop_if_fatal(st)
    last, hdr, top_end, n = st["last"], st["hdr"], st["top_end"], st["n_top"]
    print(f"== {st['brand']}「{st['title']}」修正本期已貼的內容（不插欄）==")
    print(f"本期（G1）：{st['week']}｜最後週次欄：{col(last)}「{st['last_title']}」｜前一期：{col(last - 1)}「{st['prev_title']}」")
    if not done_already(st):
        print("本期還沒貼（G1 和最後週次欄的標題不同），repair 不適用，沒有寫入。請用 run。")
        sys.exit(1)
    al = alignment(st)
    if not al["ok"] or not st["prev_is_rank"]:
        print("停止：下方表和上方關鍵字對不起來，或前一欄不是大字排名，沒有寫入。請先用 check 看細節。")
        sys.exit(1)

    reqs, plan, todo, expect = [], [], [], {}
    # C 欄：用前一期（最後週次欄的左邊那欄）逐列重貼
    exp_c = hist_col(st, 0)
    c_head = str(cell(st["low"], hdr - st["low_first"], 2))
    bad_c = diff_rows(low_col(st, 2), exp_c, hdr + 1)
    if bad_c or norm_week(c_head) != norm_week(st["prev_title"]):
        reqs += [paste_values(st, (3, top_end, last - 1, last - 1), (hdr + 1, st["low_end"], 3, 3)),
                 paste_values(st, (1, 1, last - 1, last - 1), (hdr, hdr, 3, 3))]
        plan.append(f"下方表 C{hdr + 1}:C{st['low_end']} ← {col(last - 1)}3:{col(last - 1)}{top_end} 的值（目前有 {len(bad_c)} 列不同），C{hdr} 標題是「{st['prev_title']}」")
    else:
        print(f"下方表 C 欄已經和 {col(last - 1)} 欄一致，不用修。")
    for name, c in (("C", 3), ("E", 5)):
        left = residue(st, c - 1)
        if left:
            reqs.append(clear_values(st, left[0], left[-1], c, c))
            plan.append(f"清掉下方表底下 {name}{left[0]}:{name}{left[-1]} 的殘值（{len(left)} 格）")
    # E 欄：歷史區的上一期頁面排名已被本期蓋掉，只有 run 的備份可以當來源
    path, backup = find_run_backup(st)
    if backup:
        bad_e = diff_rows(low_col(st, 4), backup["prev_page"], hdr + 1)
        if bad_e:
            reqs.append(write_column(st, hdr + 1, 5, backup["prev_page"]))
            plan.append(f"下方表 E{hdr + 1}:E{st['low_end']} ← 備份 {path.name} 裡的上一期頁面排名（目前有 {len(bad_e)} 列不同）")
            expect["e"] = backup["prev_page"]
        else:
            print("下方表 E 欄和備份裡的上一期頁面排名一致，不用修。")
    else:
        d_fixed = formula_state(st)["D"]["fixed_value"] == st["n_low"]
        hint = "目前 E 欄和 D 欄（寫死的舊值）逐列相同，看起來就是上一期的頁面排名。" if d_fixed and not diff_rows(low_col(st, 4), low_col(st, 3), 0) else ""
        print(f"下方表 E 欄不動：上一期的頁面排名在歷史區已經被本期蓋掉，也沒有 run 的備份可以當來源。{hint}")
    # 最新 7 欄：G:M 沒有 #REF! 才重貼
    refs, dups = ref_errors(st), {d["top_row"]: d for d in gsc_duplicates(st)}
    cells = latest_block_diff(st)
    if refs:
        todo.append(f"G:M 還有 #REF!，最新 7 欄（{col(last)}:{col(last + 6)}）先不重貼。請人到 GSCdata 處理後再跑一次 repair：")
        for r, kw, cols in refs:
            todo.append(f"  第 {r} 列「{kw}」的 {'、'.join(cols)} 欄")
            for x in dups.get(r, {}).get("rows", []):
                todo.append(f"    GSCdata 第 {x['row']} 列：query「{x['query']}」、page {x['page']} → {'建議刪除這一列' if x['suggest_delete'] else '保留'}")
    elif cells:
        reqs += [paste_values(st, (1, top_end, G, M), (1, top_end, last, last + 6)), clear_values(st, 1, 1, last + 1, last + 1)]
        plan.append(f"G1:M{top_end} 重新貼成值到 {col(last)}1:{col(last + 6)}{top_end}（目前有 {len(cells)} 格不同：{'、'.join(cells[:8])}{'…' if len(cells) > 8 else ''}），並清掉 {col(last + 1)}1")
    else:
        print(f"最新 7 欄（{col(last)}:{col(last + 6)}）和現在的 G:M 逐格相同，不用重貼。")

    if plan:
        print("要做的事（一次寫入）：")
        for i, p in enumerate(plan, 1):
            print(f"  {i}. {p}")
    for t in todo:
        print(f"[待人工] {t}")
    if not plan:
        print("沒有可以自動修的項目，沒有寫入。")
        sys.exit(1 if todo else 0)
    if a.dry_run:
        print(f"\n--dry-run：以上都沒有執行。正式執行時會先備份到 {DRAFTS}\\article_list_backup_{st['brand']}_<時間>.json")
        return
    book.guard()
    save_backup(st, "repair", {})
    unchanged_or_exit(book, st)
    book.write(reqs)
    print("已寫入，讀回驗證：")

    new = load(book)
    stop_if_fatal(new)
    bad = diff_rows(low_col(new, 2), hist_col(new, 0), hdr + 1)
    head = str(cell(new["low"], hdr - new["low_first"], 2))
    checks = [(not bad and norm_week(head) == norm_week(new["prev_title"]), f"下方表 C 欄＝{col(last - 1)} 欄「{new['prev_title']}」：{n - len(bad)}/{n} 列相同，標題「{head}」"),
              (not residue(new, 2) and not residue(new, 4), f"下方表底下 C、E 欄沒有殘值（C：{len(residue(new, 2))} 格、E：{len(residue(new, 4))} 格）"),
              (new["grid_cols"] == st["grid_cols"], f"欄數沒變：{new['grid_cols']}")]
    if "e" in expect:
        bad = diff_rows(low_col(new, 4), expect["e"], hdr + 1)
        checks.append((not bad, f"下方表 E 欄＝備份裡的上一期頁面排名：{n - len(bad)}/{n} 列相同"))
    if not refs:
        left = latest_block_diff(new)
        ref_left = sum(1 for r in range(top_end) for k in range(1, 8) if err_code(cell(new["hist"], r, k)) == "#REF!")
        checks.append((not left and not ref_left, f"最新 7 欄 {col(last)}:{col(last + 6)} 和 G:M 逐格相同：{top_end * 7 - len(left)}/{top_end * 7} 格，歷史區 #REF! 剩 {ref_left} 格"))
    ok = report(checks)
    print("\n完成。" + ("還有上面標「待人工」的項目要處理。" if todo else "") if ok else "\n有項目不符，請對照備份檔檢查。")
    sys.exit(0 if ok and not todo else 1)


def cmd_formulas(book, a):
    st = load(book)
    stop_if_fatal(st)
    hdr, n = st["hdr"], st["n_low"]
    print(f"== {st['brand']}「{st['title']}」下方表 B、D 欄改成公式 ==")
    al = alignment(st)
    if not al["ok"]:
        print(f"停止：下方表的關鍵字順序和上方第 3 列起不一致（上方 {st['n_top']} 列、下方 {n} 列），沒有寫入。不一致的列：")
        for x in al["mismatch"][:20]:
            print(f"  第 {x['top_row']} 列「{x['top']}」↔ 第 {x['low_row']} 列「{x['low']}」")
        sys.exit(1)
    print(f"下方表 {n} 列和上方關鍵字逐列對應。" + (f"其中 {len(al['loose'])} 列寫法略有不同但位置相同，視為同一個關鍵字：" if al["loose"] else ""))
    for x in al["loose"]:
        print(f"  第 {x['top_row']} 列「{x['top']}」↔ 第 {x['low_row']} 列「{x['low']}」")
    # A 欄只回報、不改
    a_formula = sum(1 for x in low_col(st, 0, formulas=True) if str(x).startswith("="))
    if st["brand"] != "HK":
        try:
            hk = load(Book("HK", ORIGINALS["HK"]))
            hk_a = sum(1 for x in low_col(hk, 0, formulas=True) if str(x).startswith("="))
            print(f"A 欄（只回報、不改）：HK 正式表下方表 A 欄 {hk['n_low']} 列裡有 {hk_a} 列是公式（=A3 這種寫法）；這份 {n} 列裡有 {a_formula} 列是公式，其餘是寫死的關鍵字。")
        except Exception as e:   # 讀不到 HK 不影響這個子命令
            print(f"A 欄（只回報、不改）：這份 {n} 列裡有 {a_formula} 列是公式。HK 正式表讀取失敗（{e}）。")
    fs = formula_state(st)
    if fs["B"]["expected"] == n and fs["D"]["expected"] == n:
        print("B、D 欄已經都是公式，不用改，沒有寫入。")
        return
    print(f"要做的事（一次寫入）：B{hdr + 1}:B{st['low_end']} 改成 =G3…=G{st['top_end']}（目前 {fs['B']['fixed_value']} 列是寫死的值）；"
          f"D{hdr + 1}:D{st['low_end']} 改成 =H3…=H{st['top_end']}（目前 {fs['D']['fixed_value']} 列是寫死的值）")
    if a.dry_run:
        print(f"\n--dry-run：以上都沒有執行。正式執行時會先備份到 {DRAFTS}\\article_list_backup_{st['brand']}_<時間>.json")
        return
    book.guard()
    save_backup(st, "formulas", {})
    unchanged_or_exit(book, st)
    book.write([write_column(st, hdr + 1, 2, [f"=G{3 + i}" for i in range(n)]),
                write_column(st, hdr + 1, 4, [f"=H{3 + i}" for i in range(n)])])
    print("已寫入，讀回驗證：")
    new = load(book)
    stop_if_fatal(new)
    fs = formula_state(new)
    bad_b, bad_d = diff_rows(low_col(new, 1), gm_col(new, 0), hdr + 1), diff_rows(low_col(new, 3), gm_col(new, 1), hdr + 1)
    ok = report([(fs["B"]["expected"] == n, f"B 欄公式：{fs['B']['expected']}/{n} 列"),
                 (fs["D"]["expected"] == n, f"D 欄公式：{fs['D']['expected']}/{n} 列"),
                 (not bad_b, f"B 欄算出來的值＝G 欄：{n - len(bad_b)}/{n} 列相同"),
                 (not bad_d, f"D 欄算出來的值＝H 欄：{n - len(bad_d)}/{n} 列相同")])
    print("\n完成。" if ok else "\n有項目不符，請對照備份檔檢查。")
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(description="文章與數據列表「核心關鍵字追蹤」每週更新")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, doc in (("check", cmd_check, "唯讀檢查"), ("run", cmd_run, "每週更新"),
                          ("repair", cmd_repair, "修正本期已貼的內容"), ("formulas", cmd_formulas, "下方表 B、D 欄改成公式")):
        p = sub.add_parser(name, help=doc)
        p.add_argument("brand", choices=sorted(ORIGINALS))
        p.add_argument("--sheet-id", help="試算表 ID，預設是正式表；測試請指定 [TEST] 開頭的副本")
        if name == "check":
            p.add_argument("--json", action="store_true", help="輸出 JSON")
        else:
            p.add_argument("--dry-run", action="store_true", help="只列出要做的事，不寫入")
            p.add_argument("--allow-original", action="store_true", help="允許寫入正式表")
        p.set_defaults(fn=fn)
    a = ap.parse_args()
    book = Book(a.brand, a.sheet_id or ORIGINALS[a.brand], getattr(a, "allow_original", False))
    a.fn(book, a)


if __name__ == "__main__":
    main()
