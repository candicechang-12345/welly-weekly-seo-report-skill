# 第一次設定

給第一次在自己電腦跑每週數據報告的人。全部做完大約 20 分鐘，需要能登入 welly.seo.team 的 Chrome。不需要 GitHub 帳號。

## 誰在哪裡跑

| 工作 | 在哪裡跑 | 用哪個帳號 |
|---|---|---|
| 複製報告文件、數據表格、GSC 介面三項、DR／UR、卡片截圖、文字草稿、執行紀錄 | 本機 Claude 桌面版（排程週四 09:00，或手動說「跑本週數據報告」） | Google：welly.seo.team（OAuth）；Chrome 要登入 welly.seo.team |
| 文章與數據列表、外鏈域名紀錄、貼 Slack | 人工 | welly.seo.team |

## 要準備的東西

1. **軟體**：Python 3.12 以上、Google Chrome、Claude 桌面版，Chrome 裝好 Claude in Chrome 擴充功能。
2. **Chrome 設定檔**：新增一個 Chrome 設定檔，登入 welly.seo.team（驗證碼找佳勳，只要一次），並在這個設定檔裝好、連上 Claude in Chrome。登入由本人操作，Claude 不輸入帳密或驗證碼。
3. **金鑰資料夾** `%USERPROFILE%\.welly-seo\`（自己建立），向流程負責人拿下面的檔案，自己放進去。不要放進工作資料夾，不要貼到對話或 Slack。

| 檔案 | 內容 | 必要嗎 |
|---|---|---|
| `client_secret.json` | Google OAuth 用戶端檔 | 必要 |
| `ahrefs.env` | 一行 `AHREFS_API_KEY=…` | 必要（DR／UR、SERP）。沒有時 DR／UR 改用 Chrome 讀或留給人工 |
| `dataforseo.env` | 兩行 `DATAFORSEO_LOGIN=…`、`DATAFORSEO_PASSWORD=…` | 選用。沒有時 Haveababy 草稿照常產生，只少了搜尋熱度驗證，回報會出現「DataForSEO 搜尋熱度沒抓到」 |
| `token.json` | 授權後程式自己產生，等同密碼 | 不用拿，第 3 步會產生 |
| `config.json` | 個人設定，程式自己產生 | 不用拿，第 4 步會產生 |

## 設定步驟

請 Claude「初始化每週數據報告」，它會照下面做；也可以自己在 PowerShell 做。`<技能資料夾>` 是技能安裝的位置（SKILL.md 所在的資料夾）。

1. **建工作資料夾並複製程式**
   ```powershell
   $W = "$env:USERPROFILE\welly-weekly-seo-report"
   New-Item -ItemType Directory -Force "$W\scripts", "$W\drafts" | Out-Null
   Copy-Item "<技能資料夾>\scripts\*" "$W\scripts\" -Force
   ```
2. **建 Python 環境**
   ```powershell
   python -m venv "$W\.venv"
   & "$W\.venv\Scripts\python" -m pip install -r "$W\scripts\requirements.txt"
   ```
3. **Google 授權（只要一次）**
   ```powershell
   & "$W\.venv\Scripts\python" "$W\scripts\welly_auth.py" --local
   ```
   會開瀏覽器。在登入 welly.seo.team 的那個 Chrome 視窗完成授權頁（看到「未驗證」按「進階 → 繼續」）。成功後金鑰資料夾會有 `token.json`，含 5 個權限：GSC 唯讀、GA4 唯讀、試算表、雲端硬碟唯讀、只能改程式自己建立的檔案。
4. **個人設定**（工作目錄 `$W\scripts`）
   ```powershell
   & "$W\.venv\Scripts\python" local_config.py set operator <你的名字>
   & "$W\.venv\Scripts\python" local_config.py show
   ```
   - `operator`：「週報執行紀錄」上顯示的負責人。沒設就用電腦登入名稱。
   - `gsc_user`：welly.seo.team 是這台 Chrome 的第幾個帳號（從 0 算，預設 1）。第一次跑的時候 Claude 會試出來並存好。
   - `handover_folder`：放「週報執行紀錄」的雲端資料夾，用預設值，不用改。
5. **確認**
   ```powershell
   & "$W\.venv\Scripts\python" welly_auth.py --check          # 列得出 welly.tw、welly.hk、haveababy.tw
   & "$W\.venv\Scripts\python" copy_weekly_doc.py --dry-run   # 找得到上週文件
   & "$W\.venv\Scripts\python" run_log.py check               # 讀得到週報執行紀錄
   & "$W\.venv\Scripts\python" ahrefs_api.py dr-ur --date <上週日> welly.tw
   ```
6. **建排程**（選用）：照 `schedule_prompt.md` 的「怎麼建排程」。代班只跑一兩次的話不用建，週四對 Claude 說「跑本週數據報告」就可以。

## 怎麼知道這週跑過了沒

打開雲端硬碟交接資料夾裡的「週報執行紀錄」試算表，找當週那一列：
- 「已完成」→ 這週跑完了，同一列有新報告文件連結與回報內容。
- 「填表中」→ 某台電腦正在跑。超過 3 小時還在，代表上次中斷，再跑一次就會重做。
- 「未完成」→ 看回報裡的原因，修好後再跑一次。
- 沒有這一列 → 還沒有電腦跑過，對 Claude 說「跑本週數據報告」。

## 技能更新之後

技能有新版時，每週執行開頭會把技能資料夾的 `scripts\` 複製到工作資料夾蓋掉舊版，不用手動處理。`requirements.txt` 有變動時，重跑第 2 步的 pip install。

## 出問題時

- **授權失效**（welly.seo.team 改密碼、撤銷存取權、半年沒用）：重做第 3 步。
- **GSC 顯示沒有存取權限**：帳號序號不對。請 Claude 重新試 /u/0/、/u/1/、/u/2/，或自己 `local_config.py set gsc_user <數字>`。
- **Chrome 要登入或要驗證碼**：自己登入，Claude 不代登。
- **GA4 缺資料警告**：資料還沒進來，過幾小時請 Claude 重跑，表格會原地換新。
- **換電腦或交接完成**：刪掉舊電腦的 `%USERPROFILE%\.welly-seo\` 和 Claude 排程。忘了刪也不會重複填，執行紀錄會擋。
- **想全部停用**：welly.seo.team 的 Google 帳戶 →「安全性」→「第三方存取權」移除這個應用程式；關閉 Claude 排程。
