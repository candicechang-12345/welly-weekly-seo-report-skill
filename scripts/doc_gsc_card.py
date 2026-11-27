"""把 GSC 彩色指標卡片截圖插進當週報告文件，放在該品牌數據表格正上方，取代上週留下的卡片圖。

截圖由排程用 Claude in Chrome 截（scheduled_task_prompt.md 步驟 5.2），這支程式只負責放進文件：
  1. 圖檔上傳到 welly.seo.team 雲端硬碟（drive.file），暫時開「知道連結的人可檢視」——Docs API 只能用網址插圖
  2. 插進文件，寬度 451pt（頁面內容寬，和過去截圖一樣）
  3. 刪掉雲端硬碟的暫存檔（文件裡會保留自己的副本）

位置：從該品牌表格（doc_data_table.py 產生）往前跳過空段落，碰到高度 ≤ 200 的圖 → 換掉；沒有圖 → 插在表格前的空段落。
所以要先跑 doc_data_table.py 再跑這支。

用法（工作目錄 scripts）：
  python doc_gsc_card.py Welly --week 2026-11-16 --doc <文件ID> --image <截圖.png> [--dry-run]
寫入限制同 draft_welly.py：[TEST] 副本，或 copy_weekly_doc.py 建立的該週報告文件。
"""

import argparse
import datetime as dt
import json
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession

from copy_weekly_doc import DOCS, DRIVE
from doc_data_table import TITLES, find_tables, image_height, ptext, region
from draft_welly import check_doc
from welly_auth import LOCAL_SCOPES, load_credentials

UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
WIDTH_PT = 451
CARD_MAX_HEIGHT = 200   # 文件裡卡片圖約 95～100pt 高，試算表截圖約 250～300pt


def target(d, brand):
    """回傳 ("replace", 舊圖 index) 或 ("insert", 空段落 index)。"""
    elements, _ = region(d, brand)
    table = find_tables(elements).get(TITLES[brand])
    if not table:
        raise SystemExit(f"{TITLES[brand]} 段落裡找不到數據表格，請先跑 doc_data_table.py")
    i = elements.index(table) - 1
    empty = None
    while i >= 0 and "paragraph" in elements[i]:
        el = elements[i]
        h = image_height(d, el)
        if h is not None:
            if h > CARD_MAX_HEIGHT:
                break
            img = next(e for e in el["paragraph"]["elements"] if "inlineObjectElement" in e)
            return "replace", img["startIndex"]
        if ptext(el):
            break
        empty = empty or el["startIndex"]
        i -= 1
    if empty is None:
        raise SystemExit(f"{TITLES[brand]} 表格前沒有可放圖的空段落，版面和預期不同，請人工處理")
    return "insert", empty


def upload(s, path):
    meta = {"name": f"gsc-card-{Path(path).stem}.png", "mimeType": "image/png"}
    boundary = "welly-gsc-card"
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{boundary}\r\nContent-Type: image/png\r\n\r\n").encode() + Path(path).read_bytes() + f"\r\n--{boundary}--".encode()
    r = s.post(UPLOAD, params={"uploadType": "multipart"}, data=body,
               headers={"Content-Type": f"multipart/related; boundary={boundary}"})
    r.raise_for_status()
    fid = r.json()["id"]
    s.post(f"{DRIVE}/{fid}/permissions", json={"type": "anyone", "role": "reader"}).raise_for_status()
    return fid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("brand", choices=list(TITLES))
    ap.add_argument("--week", required=True, help="報告週的週一（文件所屬週）YYYY-MM-DD")
    ap.add_argument("--doc", required=True)
    ap.add_argument("--image", required=True, help="Chrome 截好的卡片 PNG")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    s = AuthorizedSession(load_credentials(allow_browser=False, scopes=LOCAL_SCOPES))
    name = check_doc(s, a.doc, dt.date.fromisoformat(a.week))
    d = s.get(f"{DOCS}/{a.doc}").json()
    mode, at = target(d, a.brand)
    print(f"{a.brand}：{'換掉舊卡片圖' if mode == 'replace' else '插在表格前'}（index {at}）→ {name}")
    if a.dry_run:
        print("dry-run，沒有寫入")
        return

    fid = upload(s, a.image)
    try:
        reqs = [{"deleteContentRange": {"range": {"startIndex": at, "endIndex": at + 1}}}] if mode == "replace" else []
        reqs.append({"insertInlineImage": {"location": {"index": at},
                                           "uri": f"https://lh3.googleusercontent.com/d/{fid}",
                                           "objectSize": {"width": {"magnitude": WIDTH_PT, "unit": "PT"}}}})
        r = s.post(f"{DOCS}/{a.doc}:batchUpdate", json={"requests": reqs})
        if not r.ok:
            raise SystemExit(f"插圖失敗：{r.status_code} {r.text[:500]}")
    finally:
        s.delete(f"{DRIVE}/{fid}")
    print(f"已插入卡片圖：https://docs.google.com/document/d/{a.doc}/edit")


if __name__ == "__main__":
    main()
