"""Welly TW 週報、Welly HK 月報的「整體來看」文字草稿，寫進當週報告文件的【Welly】【Welly HK】段落。

句型照 2026/9～10 月報告（範本：drafts/samples/welly_hk_sections.json）：
  【Welly】整體來看：本週整站排名下降 0.4 至 8.7，整站曝光減少 8,031 次，點擊減少 195 次。
           重點大字追蹤：【SEO】：大字排名與上週上升 1.1 至 26.6，曝光增加 17 次、點擊不變，目前無痕第三頁。
                         【SEO公司】：大字排名與上週相比上升 3 至 5.4，曝光增加 12 次，點擊減少 2 次，目前無痕第二頁，有出現在 AIO。
  【Welly HK】整體來看：本月相較於上月整站曝光減少 13,402 次，點擊減少 19 次，平均排名上升 5.6 至 32.2。
排名數字取 GSC 平均排名四捨五入到小數 1 位再相減（跟過去報告一致）。黑字照過去報告標黃底（#FFFF00）。每點底下有灰字「數據」，發到 Slack 前刪掉。

用法（工作目錄 scripts，Python 用 .venv）：
  python draft_welly.py preview --week 2026-10-12                 # 只印草稿，不碰文件（核對過去報告用）
  python draft_welly.py write --week 2026-10-26 --doc <文件ID> [--notes notes.json] [--dry-run] [--force]

notes.json（排程用 Chrome 查完大字排名後寫，沒有也能跑，缺的地方標【待確認】）：
  {"serp_source": "Chrome（SEO Welly 設定檔，pws=0）11/5",
   "serp": {"SEO": {"rank": "無痕第三頁", "aio": false, "target_page": false},
            "SEO公司": {"rank": "無痕第二頁", "aio": true, "target_page": true}}}
  新站（wellyblog.tw）同樣格式寫在 "serp_new"：{"SEO": {"rank": "沒有出現在無痕前五頁", "aio": false}, ...}
  rank 照過去寫法：首頁寫「無痕第 8 名」，其他寫「無痕第二頁」「無痕第三頁」，前五頁都沒有寫「沒有出現在無痕前五頁」。
  target_page＝false 代表搜到的是別篇文章，句子會加「非大字頁面文章」。

新站（2026-11-17 起）：Welly TW 轉移到 https://wellyblog.tw/ 期間，【Welly】段落的整體與大字句子都分成【舊站】【新站】兩行。
新站 GSC 用網址前置字元資源 https://wellyblog.tw/（台灣），大字只篩查詢（完全相符）、不篩頁，灰字標出曝光最多的頁面；
新站 GA4（562289258）總工作階段放在灰字「數據」。

寫入限制：標題「[TEST]」開頭的副本；或 copy_weekly_doc.py 建立的當週報告文件（2026/10/26 那週以後）。
【Welly HK】只在月報週寫。段落裡已有「Claude 草稿」就跳過該段（使用者可能改過），要重寫加 --force。
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession

from copy_weekly_doc import DOCS, DRIVE, TITLE_RE
from draft_analysis import P, gray, requests_for, to_text, utf16_len  # noqa: F401
from weekly_plan import plan
from welly_auth import LOCAL_SCOPES, load_credentials

FIRST_WEEK = dt.date(2026, 10, 26)
MARKER = "〔Claude 草稿"
OUT_DIR = Path(__file__).resolve().parent.parent / "drafts"
# 大字 → 主攻頁（和 welly_weekly.py 相同；查詢＋頁、完全相符）
KEYWORDS = {
    "SEO": ("seo", "https://welly.tw/blog/what-is-seo", "大字排名與上週"),
    "SEO公司": ("seo公司", "https://welly.tw/blog/how-to-choose-seo-agency", "大字排名與上週相比"),
}
NEW_SITE = {"gsc": "https://wellyblog.tw/", "ga4": "562289258", "country": "twn", "host": "https://wellyblog.tw"}
SECTIONS = {   # 段落標題關鍵字 → (結尾段落文字, GSC 資源, 國家)
    "Welly": ("【Welly】", "本週 vs 上週", "sc-domain:welly.tw", "twn"),
    "WellyHK": ("【Welly HK】", "本月 vs 上月", "sc-domain:welly.hk", "hkg"),
}


# ---------- 數據 ----------

def gsc(s, site, country, start, end, filters=()):
    url = f"https://www.googleapis.com/webmasters/v3/sites/{quote(site, safe='')}/searchAnalytics/query"
    flt = [{"dimension": "country", "operator": "equals", "expression": country}]
    flt += [{"dimension": d, "operator": "equals", "expression": v} for d, v in filters]
    r = s.post(url, json={"startDate": start, "endDate": end, "dimensionFilterGroups": [{"filters": flt}]})
    r.raise_for_status()
    rows = r.json().get("rows")
    if not rows or not rows[0]["impressions"]:   # 沒曝光時 GSC 會回排名 0，當成沒有排名
        return {"clicks": 0, "impressions": 0, "position": None}
    return {"clicks": int(rows[0]["clicks"]), "impressions": int(rows[0]["impressions"]),
            "position": round(rows[0]["position"], 1)}


def gsc_top_page(s, site, country, start, end, query):
    """新站大字：查詢完全相符時，曝光最多的頁面（新站主攻頁還沒定，先看實際排上去的是哪篇）。"""
    url = f"https://www.googleapis.com/webmasters/v3/sites/{quote(site, safe='')}/searchAnalytics/query"
    flt = [{"dimension": "country", "operator": "equals", "expression": country},
           {"dimension": "query", "operator": "equals", "expression": query}]
    r = s.post(url, json={"startDate": start, "endDate": end, "dimensions": ["page"], "rowLimit": 5,
                          "dimensionFilterGroups": [{"filters": flt}]})
    r.raise_for_status()
    rows = sorted(r.json().get("rows", []), key=lambda x: -x["impressions"])
    return rows[0]["keys"][0] if rows else None


def ga4_sessions(s, prop, start, end):
    r = s.post(f"https://analyticsdata.googleapis.com/v1beta/properties/{prop}:runReport",
               json={"dateRanges": [{"startDate": start, "endDate": end}], "metrics": [{"name": "sessions"}]})
    r.raise_for_status()
    rows = r.json().get("rows")
    return int(rows[0]["metricValues"][0]["value"]) if rows else 0


def gsc_last_date(s, site, start, end):
    url = f"https://www.googleapis.com/webmasters/v3/sites/{quote(site, safe='')}/searchAnalytics/query"
    r = s.post(url, json={"startDate": start, "endDate": end, "dimensions": ["date"], "rowLimit": 400})
    r.raise_for_status()
    days = [x["keys"][0] for x in r.json().get("rows", [])]
    return max(days) if days else None


def collect(s, monday):
    sunday = monday + dt.timedelta(days=6)
    cur = (monday.isoformat(), sunday.isoformat())
    prev = ((monday - dt.timedelta(days=7)).isoformat(), (monday - dt.timedelta(days=1)).isoformat())
    _, site, country = SECTIONS["Welly"][1:]
    data = {"week": cur, "prev_week": prev, "warnings": [],
            "site": {"cur": gsc(s, site, country, *cur), "prev": gsc(s, site, country, *prev)}, "keywords": {}}
    last = gsc_last_date(s, site, *cur)
    if last != cur[1]:
        data["warnings"].append(f"welly.tw GSC 資料只到 {last}")
    for k, (q, page, _) in KEYWORDS.items():
        f = [("query", q), ("page", page)]
        data["keywords"][k] = {"query": q, "page": page,
                               "cur": gsc(s, site, country, *cur, filters=f), "prev": gsc(s, site, country, *prev, filters=f)}
    ns, nc = NEW_SITE["gsc"], NEW_SITE["country"]
    data["new"] = {"site": {"cur": gsc(s, ns, nc, *cur), "prev": gsc(s, ns, nc, *prev)}, "keywords": {},
                   "ga4": {"cur": ga4_sessions(s, NEW_SITE["ga4"], *cur), "prev": ga4_sessions(s, NEW_SITE["ga4"], *prev)}}
    last = gsc_last_date(s, ns, *cur)
    if last != cur[1]:
        data["warnings"].append(f"wellyblog.tw（新站）GSC 資料只到 {last}")
    for k, (q, _, _) in KEYWORDS.items():
        f = [("query", q)]
        data["new"]["keywords"][k] = {"query": q, "page": gsc_top_page(s, ns, nc, *cur, q),
                                      "cur": gsc(s, ns, nc, *cur, filters=f), "prev": gsc(s, ns, nc, *prev, filters=f)}
    monthly = plan(sunday + dt.timedelta(days=4))["monthly"]
    if monthly:
        y, m = monthly
        ms = dt.date(y, m, 1)
        me = (ms.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        pe = ms - dt.timedelta(days=1)
        ps = pe.replace(day=1)
        _, site, country = SECTIONS["WellyHK"][1:]
        data["hk"] = {"month": f"{y}-{m:02d}", "cur_range": (ms.isoformat(), me.isoformat()),
                      "prev_range": (ps.isoformat(), pe.isoformat()),
                      "cur": gsc(s, site, country, ms.isoformat(), me.isoformat()),
                      "prev": gsc(s, site, country, ps.isoformat(), pe.isoformat())}
        last = gsc_last_date(s, site, ms.isoformat(), me.isoformat())
        if last != me.isoformat():
            data["warnings"].append(f"welly.hk GSC 資料只到 {last}")
    return data


# ---------- 句子 ----------

def Y(level, text):
    """黃底黑字：過去報告 Welly、Welly HK 段落的黑字（整體來看、重點大字追蹤、每一句）都標黃底，灰字「數據」不標。"""
    return P(level, (text, "y"))


def num(x):
    return f"{x:g}" if isinstance(x, float) else str(x)


def rank_move(prev, cur, same_word="不變為"):
    if cur is None:
        return "沒有排名數據"
    if prev is None:
        return f"新出現，排名 {num(cur)}"
    d = round(prev - cur, 1)
    if d == 0:
        return f"{same_word} {num(cur)}"
    return f"{'上升' if d > 0 else '下降'} {num(abs(d))} 至 {num(cur)}"


def count_move(label, prev, cur, unit="次"):
    d = cur - prev
    if d == 0:
        return f"{label}不變"
    return f"{label}{'增加' if d > 0 else '減少'} {abs(d):,} {unit}"


def md(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.month}/{d.day}"


def data_line(prev, cur):
    pos = lambda p: "無" if p is None else num(p)
    return (f"點擊 {prev['clicks']:,} → {cur['clicks']:,}，曝光 {prev['impressions']:,} → {cur['impressions']:,}，"
            f"平均排名 {pos(prev['position'])} → {pos(cur['position'])}")


def keyword_sentence(k, kw, sv, tag="", check_page=True):
    _, _, lead = KEYWORDS[k]
    c, p = kw["cur"], kw["prev"]
    if c["position"] is None and p["position"] is None:
        txt = f"{tag}【{k}】：本週與上週都還沒有曝光，"
    else:
        txt = (f"{tag}【{k}】：{lead}{rank_move(p['position'], c['position'])}，"
               f"{count_move('曝光', p['impressions'], c['impressions'])}、{count_move('點擊', p['clicks'], c['clicks'])}，")
    if sv.get("rank"):
        txt += f"目前{sv['rank']}"
        if check_page and sv.get("target_page") is False:
            txt += "非大字頁面文章"
    else:
        txt += "目前無痕排名【待確認】"
    if sv.get("aio") is True:
        txt += "，有出現在 AIO"
    return txt + "。"


def site_sentence(tag, p, c):
    return (f"{tag}本週整站排名{rank_move(p['position'], c['position'])}，"
            f"整站{count_move('曝光', p['impressions'], c['impressions'])}，{count_move('點擊', p['clicks'], c['clicks'])}。")


def build_welly(data, notes):
    """沒有新站資料時照過去報告（黑字全黃底）。
    有新站時照使用者 2026-11-19 改的版面：「整體來看：」下分【舊站】【新站】兩個小標（不加項目符號），
    各自底下是整站一句、空行、重點大字追蹤與大字句子（句子不再加【舊站】【新站】前綴）；
    舊站整塊不標黃底，新站整塊（含小標）標黃底。灰字「數據」照舊跟在每句下面，發到 Slack 前刪掉。"""
    new = data.get("new")
    rng = f"{md(data['week'][0])}～{md(data['week'][1])} vs {md(data['prev_week'][0])}～{md(data['prev_week'][1])}"
    c, p = data["site"]["cur"], data["site"]["prev"]
    old_kw = [(k, keyword_sentence(k, kw, notes.get("serp", {}).get(k, {})),
               f"查詢「{kw['query']}」＋頁 {kw['page'].replace('https://welly.tw', '')}（完全相符），{data_line(kw['prev'], kw['cur'])}")
              for k, kw in data["keywords"].items()]
    if not new:
        nodes = [Y(0, "整體來看："), Y(1, site_sentence("", p, c)),
                 gray(2, "數據", f"GSC 台灣 {rng}，{data_line(p, c)}"), Y(1, "重點大字追蹤：")]
        for _, sentence, dl in old_kw:
            nodes += [Y(2, sentence), gray(3, "數據", dl)]
        return nodes

    def block(label, hl, site_line, site_data, kws):
        mark = (lambda lvl, t: Y(lvl, t)) if hl else (lambda lvl, t: P(lvl, t))
        out = [mark(None, label), mark(1, site_line), gray(2, "數據", site_data), mark(None, ""),
               mark(1, "重點大字追蹤：")]
        for _, sentence, dl in kws:
            out += [mark(2, sentence), gray(3, "數據", dl)]
        return out

    nc, np_ = new["site"]["cur"], new["site"]["prev"]
    new_kw = []
    for k in data["keywords"]:
        nk = new["keywords"][k]
        page = nk["page"].replace(NEW_SITE["host"], "") if nk["page"] else "本週沒有排名"
        new_kw.append((k, keyword_sentence(k, nk, notes.get("serp_new", {}).get(k, {}), check_page=False),
                       f"wellyblog.tw 查詢「{nk['query']}」（完全相符，不篩頁；曝光最多的頁面：{page}），{data_line(nk['prev'], nk['cur'])}"))
    return ([P(0, "整體來看："), P(None, "")]
            + block("【舊站】", False, site_sentence("", p, c), f"welly.tw GSC 台灣 {rng}，{data_line(p, c)}", old_kw)
            + [P(None, "")]
            + block("【新站】", True, site_sentence("", np_, nc),
                    f"wellyblog.tw GSC 台灣 {rng}，{data_line(np_, nc)}；"
                    f"GA4 總工作階段 {new['ga4']['prev']:,} → {new['ga4']['cur']:,}", new_kw))


def build_hk(data):
    h = data["hk"]
    c, p = h["cur"], h["prev"]
    return [Y(0, "整體來看："),
            Y(1, f"本月相較於上月整站{count_move('曝光', p['impressions'], c['impressions'])}，"
                 f"{count_move('點擊', p['clicks'], c['clicks'])}，平均排名{rank_move(p['position'], c['position'])}。"),
            gray(2, "數據", f"GSC 香港 {md(h['cur_range'][0])}～{md(h['cur_range'][1])} vs "
                           f"{md(h['prev_range'][0])}～{md(h['prev_range'][1])}，{data_line(p, c)}")]


# ---------- Google 文件 ----------

def ptext(el):
    return "".join(e.get("textRun", {}).get("content", "") for e in el.get("paragraph", {}).get("elements", [])).strip()


def is_heading(el):
    return el.get("paragraph", {}).get("paragraphStyle", {}).get("namedStyleType", "").startswith("HEADING")


def find_section(d, key):
    """標題（例如【Welly】）之後、結尾段落（本週 vs 上週）之前的段落。"""
    title, end_text = SECTIONS[key][0], SECTIONS[key][1]
    content = d["body"]["content"]
    head = next((i for i, el in enumerate(content) if is_heading(el) and ptext(el).startswith(title)), None)
    if head is None:
        raise ValueError(f"找不到{title}標題")
    end = next((i for i in range(head + 1, len(content)) if ptext(content[i]) == end_text or is_heading(content[i])), None)
    if end is None or ptext(content[end]) != end_text:
        raise ValueError(f"{title}段落裡找不到「{end_text}」，版面和預期不同，請人工處理")
    stop = end
    while stop - 1 > head and not ptext(content[stop - 1]) and "inlineObjectElement" not in json.dumps(content[stop - 1]):
        stop -= 1
    if any("paragraph" not in el for el in content[head + 1:stop]):
        raise ValueError(f"{title}段落裡有表格或其他物件，版面和預期不同，請人工處理")
    body = "".join(ptext(el) for el in content[head + 1:stop])
    return {"heading": ptext(content[head]), "start": content[head]["endIndex"],
            "end": content[stop]["startIndex"], "body": body}


def check_doc(s, doc_id, monday):
    meta = s.get(f"{DRIVE}/{doc_id}", params={"fields": "name,capabilities/canEdit", "supportsAllDrives": True}).json()
    name = meta.get("name", "")
    if not meta.get("capabilities", {}).get("canEdit"):
        raise SystemExit(f"沒有編輯權限：{name}（drive.file 只能改本程式建立的文件）")
    if not name.startswith("[TEST]"):
        m = TITLE_RE.match(name)
        if not m:
            raise SystemExit(f"拒絕寫入：「{name}」不是週報文件，也不是 [TEST] 副本")
        start = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if start < FIRST_WEEK:
            raise SystemExit(f"拒絕寫入：{name} 早於 {FIRST_WEEK} 那週（同事的紀錄）")
        if start != monday:
            raise SystemExit(f"拒絕寫入：{name} 不是 {monday} 那週的報告")
    return name


def write(s, doc_id, data, notes, dry_run, force):
    monday = dt.date.fromisoformat(data["week"][0])
    name = check_doc(s, doc_id, monday)
    jobs = [("Welly", build_welly(data, notes),
             f"{md(data['week'][0])}~{md(data['week'][1])}")]
    if "hk" in data:
        h = data["hk"]
        jobs.append(("WellyHK", build_hk(data), f"{md(h['cur_range'][0])}-{md(h['cur_range'][1])}"))
    gen = dt.date.today().isoformat()
    results = []
    # 後面的段落先寫，前面段落的位置才不會跑掉
    d = s.get(f"{DOCS}/{doc_id}").json()
    secs = {}
    for key, _, label in jobs:
        try:
            sec = find_section(d, key)
        except ValueError as e:
            results.append(f"{key}：略過，{e}")
            continue
        if label not in sec["heading"]:
            results.append(f"{key}：略過，標題是「{sec['heading']}」，不是 {label}（先跑 copy_weekly_doc.py 改標題）")
            continue
        if MARKER in sec["body"] and not force:
            results.append(f"{key}：略過，段落裡已經有 Claude 草稿（可能已被修改）；要重寫請加 --force")
            continue
        secs[key] = sec
    for key, nodes, _ in sorted(jobs, key=lambda j: -secs[j[0]]["start"] if j[0] in secs else 0):
        if key not in secs:
            continue
        sec = secs[key]
        header = f"{MARKER}｜{gen} 產生〕數字來自 GSC API，請檢查後再發到 Slack；發到 Slack 前刪掉這行和灰字的「數據」。"
        if key == "Welly":
            header += f" 大字排名：{notes.get('serp_source', '沒有查，請用無痕補上')}。"
            if "new" in data:
                header += " 【新站】是 wellyblog.tw（轉移期間舊站、新站並列）。"
        for w in data["warnings"]:
            if ("welly.hk" in w) == (key == "WellyHK"):
                header += f" ⚠ {w}"
        reqs, styles = requests_for(nodes, header, sec["start"])
        if sec["end"] > sec["start"]:
            reqs.insert(0, {"deleteContentRange": {"range": {"startIndex": sec["start"], "endIndex": sec["end"]}}})
        print(f"\n## {sec['heading']}（取代 {sec['start']}～{sec['end']}）\n{header}\n{to_text(nodes)}")
        if dry_run:
            results.append(f"{key}：dry-run，沒有寫入")
            continue
        for batch in (reqs, styles):
            r = s.post(f"{DOCS}/{doc_id}:batchUpdate", json={"requests": batch})
            if not r.ok:
                raise SystemExit(f"{key} 寫入失敗：{r.status_code} {r.text[:500]}")
        results.append(f"{key}：已寫入")
    print(f"\n文件：{name}  https://docs.google.com/document/d/{doc_id}/edit")
    for line in results:
        print(line)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("preview", "write"):
        c = sub.add_parser(name)
        c.add_argument("--week", required=True, help="報告週的週一 YYYY-MM-DD")
        c.add_argument("--notes")
        if name == "write":
            c.add_argument("--doc", required=True)
            c.add_argument("--dry-run", action="store_true")
            c.add_argument("--force", action="store_true")
    a = ap.parse_args()
    monday = dt.date.fromisoformat(a.week)
    if monday.weekday() != 0:
        sys.exit("--week 要給週一")
    s = AuthorizedSession(load_credentials(allow_browser=False, scopes=LOCAL_SCOPES))
    data = collect(s, monday)
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"{a.week}_Welly_draft_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    notes = json.loads(Path(a.notes).read_text(encoding="utf-8")) if a.notes else {}
    for w in data["warnings"]:
        print("⚠", w)
    if a.cmd == "preview":
        print(to_text(build_welly(data, notes)))
        if "hk" in data:
            print("--- Welly HK ---")
            print(to_text(build_hk(data)))
        return
    write(s, a.doc, data, notes, a.dry_run, a.force)


if __name__ == "__main__":
    main()
