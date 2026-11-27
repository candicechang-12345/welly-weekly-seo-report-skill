"""每台電腦自己的設定，放在 %USERPROFILE%\\.welly-seo\\config.json（不進 repo、不進技能包）。

  python scripts/local_config.py show
  python scripts/local_config.py set gsc_user 0      # welly.seo.team 是這台 Chrome 的第幾個帳號（從 0 算）
  python scripts/local_config.py set operator 王小明  # 執行紀錄上顯示的負責人

沒有設定檔時用 DEFAULTS。換人、換電腦只改這個檔，不用改程式。
"""

import getpass
import json
import os
import sys
from pathlib import Path

CRED_DIR = Path(os.environ.get("WELLY_SEO_CRED_DIR", Path.home() / ".welly-seo"))
CONFIG = CRED_DIR / "config.json"
DEFAULTS = {
    "gsc_user": 1,      # GSC 網址的 /u/<N>/
    "operator": "",     # 空白就用電腦登入名稱
    # 交接用的雲端資料夾：週報執行紀錄放這裡
    "handover_folder": "1nIRqcVYNE2gkZyxOhN-vBn36ebWSkWL5",
}
INT_KEYS = {"gsc_user"}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG.exists():
        cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    if not cfg["operator"]:
        cfg["operator"] = getpass.getuser()
    return cfg


def main():
    args = sys.argv[1:]
    if args[:1] == ["set"] and len(args) == 3 and args[1] in DEFAULTS:
        saved = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
        saved[args[1]] = int(args[2]) if args[1] in INT_KEYS else args[2]
        CRED_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已儲存 {args[1]} = {saved[args[1]]}（{CONFIG}）")
    elif args[:1] in ([], ["show"]):
        print(json.dumps(load(), ensure_ascii=False, indent=2))
    else:
        sys.exit(f"用法：local_config.py show ｜ local_config.py set <{'|'.join(DEFAULTS)}> <值>")


if __name__ == "__main__":
    main()
