"""Google Sheets 讀寫（Sheets API v4）。

寫入規則：只能寫 WRITABLE 裡的原檔，其他試算表一律拒絕。
2026-11-18 起數據改成直接插進週報文件的表格（doc_data_table.py），「全品項數據週報」也不再寫入，WRITABLE 清空。
讀取不限制（doc_data_table.py 在文件還沒有表格時讀上期人工項目）。
"""

from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession

from welly_auth import SHEETS_SCOPES, load_credentials

API = "https://sheets.googleapis.com/v4/spreadsheets"
WEEKLY_SHEET = "1mXxcbBUIbiJKOQenyojHy0ACzjwiPhsREHaMWMVURSk"   # 全品項數據週報
MTD_SHEET = "1mXeT5C-JgHzEZyVTZwWzP_MEvO5Hg8TAdTqxd3eb3lc"      # 4.1-月累NP比較流量
WRITABLE: dict[str, str] = {}


class Sheets:
    def __init__(self):
        self.s = AuthorizedSession(load_credentials(allow_browser=False, scopes=SHEETS_SCOPES))
        self._titles = {}

    def title(self, sid: str) -> str:
        if sid not in self._titles:
            r = self.s.get(f"{API}/{sid}", params={"fields": "properties.title"})
            r.raise_for_status()
            self._titles[sid] = r.json()["properties"]["title"]
        return self._titles[sid]

    def _guard(self, sid: str):
        if sid not in WRITABLE or self.title(sid) != WRITABLE[sid]:
            raise PermissionError(f"拒絕寫入：「{self.title(sid)}」不在允許清單（只能寫 {'、'.join(WRITABLE.values())}）")

    def get(self, sid: str, rng: str, formulas: bool = False) -> list[list]:
        r = self.s.get(f"{API}/{sid}/values/{quote(rng, safe='')}",
                       params={"valueRenderOption": "FORMULA" if formulas else "UNFORMATTED_VALUE",
                               "dateTimeRenderOption": "FORMATTED_STRING"})
        r.raise_for_status()
        return r.json().get("values", [])

    def put(self, sid: str, data: dict[str, list[list]], raw: bool = False):
        """data = {A1 範圍: 二維值陣列}。預設 USER_ENTERED（照手動輸入解析）；
        raw=True 原樣寫入，等同「僅貼上值」，避免「01:37」這類文字被轉成時間。"""
        self._guard(sid)
        body = {"valueInputOption": "RAW" if raw else "USER_ENTERED",
                "data": [{"range": k, "values": v} for k, v in data.items()]}
        r = self.s.post(f"{API}/{sid}/values:batchUpdate", json=body)
        r.raise_for_status()
        return r.json()
