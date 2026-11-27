---
name: welly-weekly-seo-report
description: >
  Welly 每週內部 SEO 數據報告自動填表：複製上週「內部專案數據」報告文件、讀 GSC 介面三項、查 DR／UR、
  把 GA4／GSC／月累整理成表格插進文件、貼 GSC 指標卡片截圖、寫【Welly】【Welly HK】文字草稿，月報週加寫【HaveABaby】分析草稿，
  最後記到雲端硬碟「週報執行紀錄」並列出手動待辦與 Slack 訊息草稿。使用前初始化獨立工作副本與操作者自己的工具及憑證。
  Use when：使用者說「跑本週數據報告」「內部數據週報」「週報自動填表」「跑數據週報」「補跑週報」，
  或要做第一次設定：「從頭完成每週數據報告的第一次設定」「初始化每週數據報告」「幫我做週報的 Google 授權」「設定週報排程」「打開週報排程」「關掉週報排程」。
  使用者說「補跑文章與數據列表」時也用這個技能。不適用：客戶案的月報或成效報告、律所段落。
---

# Welly 每週內部 SEO 數據報告

每週四跑一次，報告區間是上週一到上週日。對象：welly.tw、新站 wellyblog.tw（每週），welly.hk、haveababy.tw（月報週）。

適用環境：Windows 電腦上的 Claude 桌面版，加上裝了 Claude in Chrome 的 Google Chrome。路徑與指令都是 Windows 寫法，macOS、Linux 沒有測過。

名詞：
- **技能資料夾**＝這份 SKILL.md 所在的資料夾，只讀，不在裡面執行程式、不寫檔。
- **工作資料夾**＝操作者電腦上可寫的副本，預設 `%USERPROFILE%\welly-weekly-seo-report`。裡面有 `scripts\`、`.venv\`、`drafts\`。
- **金鑰資料夾**＝`%USERPROFILE%\.welly-seo\`。金鑰只放這裡，不進技能包、不貼到對話或 Slack。

## 不做的事

- 不輸入任何密碼或驗證碼。Chrome 要登入就停下，在結尾請負責人處理。
- 不自動發 Slack。只寫好訊息草稿，負責人檢查完報告後自己貼（不需要主管審核）。
- 不動律所段落，也不動其他同事負責的品牌段落。
- 不改 2026-10-26 以前的資料。程式會拒絕，不要繞過。
- 遇到機器人驗證（CAPTCHA）就停，不嘗試通過，該項留空並列入待辦。
- 不寫 Google 試算表，只有兩個例外：「週報執行紀錄」（`run_log.py`）和兩份文章與數據列表：TW「1-Welly文章與數據列表」、「HK Welly 文章與數據列表」（`article_list.py`，只做貼值、插欄與下方表格，不刪任何資料列）。其他雲端文件只讀；程式只改 `copy_weekly_doc.py` 複製出來的那份新報告文件。
- 不用 SyncWith，不用 Ahrefs MCP 連接器（用 `ahrefs_api.py`）。
- 「已經有 Claude 草稿」時不加 `--force`，直接略過（負責人可能改過）。

要知道的一件事：`doc_gsc_card.py` 插卡片截圖時，會把圖檔暫時上傳到 welly.seo.team 的雲端硬碟並開成「知道連結的人可檢視」，讓 Google 文件抓得到圖，插完立刻刪除。這段時間很短，但圖上有整站點擊與曝光數字。

## 第一次初始化

**一句話完成**：使用者說「從頭完成每週數據報告的第一次設定」「幫我完成週報的第一次設定」，或附上金鑰檔並要求設定時，照下面 1～7 一路做到底，不要每一步都停下來等指示。只有這幾種情況才停下來請使用者動手：授權頁要他本人登入並按允許、Chrome 沒登入 welly.seo.team、電腦沒有 Python 3.12 以上（先問能不能用 `winget install Python.Python.3.12` 安裝，同意才裝）、要問名字與常態或代班。開始前先一次問完兩個問題：執行紀錄上要顯示的名字、這台電腦是常態負責還是代班備用。

第 6 步之後加做 **Chrome 檢查**：用 Claude in Chrome 列出瀏覽器，試開 `https://search.google.com/u/<N>/search-console?resource_id=sc-domain%3Awelly.tw`（N 依序試 0、1、2），找到沒有出現「沒有存取這項資源的權限」的就 `python local_config.py set gsc_user <N>`，然後關掉自己開的分頁。都開不了就列為未完成，請使用者在 Chrome 的「SEO Welly」設定檔登入 welly.seo.team（驗證碼找佳勳），不要代登。

全部做完後執行 `python run_log.py check` 確認讀得到執行紀錄（「可以執行」或「本週已完成」都算通過），最後給一張檢查表，每項標「完成」或「未完成＋要使用者做什麼」：金鑰三個檔、程式與套件、Google 授權（列得出 welly.tw、welly.hk、haveababy.tw、wellyblog.tw）、Chrome 與 Search Console、執行紀錄、排程（名稱、時間、開啟或停用）。並提醒刪掉下載資料夾裡的金鑰檔。

使用者說「初始化每週數據報告」「幫我做週報的 Google 授權」，或工作資料夾不存在時做。完整說明在 `references/setup.md`，重點：

1. **複製程式**：把 `技能資料夾\scripts\` 整個複製到 `工作資料夾\scripts\`，另建 `工作資料夾\drafts\`。
2. **建環境**：`python -m venv 工作資料夾\.venv`，再 `工作資料夾\.venv\Scripts\python -m pip install -r 工作資料夾\scripts\requirements.txt`。需要 Python 3.12 以上。
3. **放好金鑰資料夾的三個檔案**。操作者把 `client_secret.json`、`ahrefs.env`、`dataforseo.env` 附加到對話、拖進來，或說檔案在下載資料夾時，替他把檔案複製到金鑰資料夾（資料夾不存在就建立），檔名要完全一樣；下載時被改成 `ahrefs.env.txt`、`client_secret (1).json` 這類名稱的要改回來。全程不要打開、讀取或印出檔案內容，也不要把內容寫進對話、記憶或其他檔案；只回報「哪個檔案已放到哪裡」。放好後建議操作者把下載資料夾裡的那幾份刪掉。檔案來源是雲端硬碟的金鑰資料夾 https://drive.google.com/drive/folders/1vQim6IR4m4YMhsporwtOLJ69Uhvbr-XK ，沒有權限就找流程負責人。接著確認三個檔案（只看在不在）：
   - `client_secret.json`：必要。沒有就請操作者向流程負責人拿，自己放進去。
   - `ahrefs.env`：必要（DR／UR、SERP）。
   - `dataforseo.env`：選用（Haveababy 搜尋熱度驗證）。
4. **Google 授權**：`工作資料夾\.venv\Scripts\python 工作資料夾\scripts\welly_auth.py --local`。瀏覽器跳出授權頁，操作者自己用 welly.seo.team 登入並按允許（Claude 不代按、不輸入帳密）。完成後金鑰資料夾會多一個 `token.json`。
5. **個人設定**：`python local_config.py set operator <操作者名字>`（執行紀錄上顯示的負責人）。`gsc_user` 在第一次跑步驟 3 時找到後再存。
6. **確認**：`python welly_auth.py --check` 列得出網站；`python copy_weekly_doc.py --dry-run` 找得到上週文件。
7. **排程**：使用者說「設定週報排程」，或初始化做到這一步時，替操作者建立排程，不要叫他自己去介面貼提示。
   - 先問一句：這台電腦是常態負責（排程開啟），還是代班備用（先建好但關閉，代班期間再開）。
   - 用排程工具（`create_scheduled_task`，名稱依所在環境可能帶前綴；找不到就先用工具搜尋載入）建立：任務 ID `welly-weekly-seo-report`，標題「【每週四】Welly 數據週報自動填表」，cron `0 9 * * 4`（本機時間），提示用 `references/schedule_prompt.md`「貼到排程的提示」那段，把 `<工作資料夾>` 換成這台電腦實際的完整路徑。代班備用就建好後把它設成停用。
   - 已經有同名排程就更新提示，不要建第二個。
   - 建好後回報排程名稱、時間、開啟或停用。要改成開啟或停用時，操作者說「打開週報排程」「關掉週報排程」，用更新排程的工具處理。
   - 這個環境沒有排程工具時，才改成請操作者照 `references/schedule_prompt.md` 的「怎麼建排程」手動建立。

## 每週執行

共通設定：Python 一律用 `工作資料夾\.venv\Scripts\python`，設 `PYTHONIOENCODING=utf-8`，工作目錄設在 `工作資料夾\scripts`。任何步驟失敗不要硬做，記下原因後繼續其他步驟。Chrome 操作的完整細節（網址、判讀方式、截圖量測的程式碼、notes.json 格式）在 `references/schedule_prompt.md`，做到該步驟時照著做。

**開始前**：工作資料夾不存在就先做初始化。存在的話，把 `技能資料夾\scripts\` 的檔案複製過去蓋掉舊版（工作資料夾裡有 `.git` 代表是維護者的開發副本，不要蓋）。

0. **看別台電腦跑過沒**：`python run_log.py check`。結束碼 2（本週已完成或別台正在跑）→ 把輸出原文當總結，直接結束。結束碼 0 → `python run_log.py start`，再往下。
1. **確認本週範圍**：`python weekly_plan.py`。看報告區間與本週品牌（Welly、新站每週；報告週包含某月最後一天時加做 WellyHK、Haveababy 該月月報）。
2. **複製報告文件**：`python copy_weekly_doc.py`。顯示「已存在」就繼續。記下新文件連結與文件 ID。
3. **讀 GSC 介面三項**（Claude in Chrome，選有登入 welly.seo.team 的 Chrome）：每個本週品牌讀網站使用體驗核心指標、外部連結總數、最常連結的網站列數。GSC 網址的帳號序號先看 `python local_config.py show` 的 `gsc_user`；沒權限就試 0、1、2，找到後 `python local_config.py set gsc_user <數字>`。讀完關閉自己開的分頁。
4. **DR／UR**：`python ahrefs_api.py dr-ur --date <報告區間最後一天> <本週各網域>`。拿不到的改用 Chrome 開 Ahrefs 讀，仍拿不到就留空並列入待辦。
5. **數據表格**：每個品牌先加 `--dry-run` 看輸出，合理再正式跑。
   `python doc_data_table.py <Welly|WellyNew|WellyHK|Haveababy> --week <報告週一> --doc <新文件ID> --cwv <值> --links <值> --domains <值> [--dr <值> --ur <值>]`，月報品牌另加 `--month <YYYY-MM>`。記下輸出的「DOMAINS_CHANGED」「WARNING GA4 缺資料日期」「人工待填」。
   - 5.2 **GSC 指標卡片截圖**：`python weekly_plan.py --cards` 拿網址，Chrome 截四張彩色卡片，`python doc_gsc_card.py <品牌> --week <報告週一> --doc <新文件ID> --image <存檔路徑>`。截不成就跳過該品牌並列入待辦。
   - 5.4 **Welly 文字草稿**（每週，月報週含 Welly HK）：Chrome 查大字「SEO」「SEO公司」無痕前五頁排名與 AI 摘要，寫成 `工作資料夾\drafts\<報告週一>_Welly_notes.json`，`python draft_welly.py write --week <報告週一> --doc <新文件ID> --notes <notes.json> --dry-run` 看過再正式寫。
   - 5.5 **Haveababy 分析草稿**（只有月報週）：`draft_analysis.py collect` → 查 SERP（先 `ahrefs_api.py serp`，不行再用 Chrome）→ `draft_analysis.py outline` 比較文章架構 → 寫 notes.json → `draft_analysis.py write` 先 `--dry-run` 再正式寫。建議方向照 `references/haveababy_analysis.md`。查不到的不要編，留【待確認】。
   - 5.6 **文章與數據列表（TW 每週，HK 只在月報週）**：`python article_list.py check TW`（月報週再對 HK 做一輪）。有 #REF! 就不寫入，把「建議刪除這一列」的清單列進待辦，請負責人到 GSCdata 刪掉後說「補跑文章與數據列表」；沒有 #REF! 就 `run TW --dry-run` 看過再 `run TW --allow-original`。細節與補跑做法在 `references/schedule_prompt.md` 步驟 5.6。程式不刪 GSCdata 的列，`--allow-original` 只用在這一步。
6. **記到執行紀錄**：把回報內容寫成 Markdown 暫存檔。主要步驟都成功 → `python run_log.py done --body-file <檔案> --doc <新報告文件連結>`；複製文件或填表失敗 → `python run_log.py fail --body-file <檔案>`（下次可重跑）。回報內容的項目見 `references/schedule_prompt.md` 步驟 6。
7. **在對話裡給負責人總結**，格式見下一節。

數字口徑（GSC 國家、GA4 資源 ID、自然流量、月累、月報週判斷）在 `references/metrics.md`。

## 結尾回報格式

負責人可能是代班同事，寫清楚，不要用程式名稱。固定三段：

**已完成**
三五句話說做了什麼，附新報告文件連結。Welly 的數字分【舊站】【新站】兩組。

**需要你手動補上**
打勾清單。先列這次沒做成的（卡片截圖、DR／UR、【待確認】的無痕排名、GA4 缺資料要重跑、Chrome 要登入等，附連結）。再列每週固定的人工項目：執行 `python weekly_plan.py`，把各品牌「其他人工項目」裡沒有標「（自動，排程沒跑到再手動）」的照抄，標「自動」的只列這次沒抓到的。有 DOMAINS_CHANGED 就寫「⚠ <品牌> 外鏈域名 <舊> → <新>，請更新外鏈域名紀錄」並附連結。月報週要寫「檢查 Haveababy 分析草稿，刪掉灰字後發到 Slack」。

**Slack 訊息草稿**
不要自己發。照 `references/schedule_prompt.md` 步驟 7 的公版寫好可以直接複製的訊息（每週一則給 #seo內部案專用頻道，月報週另一則給 #haveababy文章討論區並提及李佳軒），字句與表情代碼照抄，只換日期、月份與報告文件連結。負責人檢查完報告後自己貼，不需要主管審核。

## 參考檔

| 檔案 | 什麼時候讀 |
|---|---|
| `references/setup.md` | 第一次設定、換電腦、授權失效 |
| `references/schedule_prompt.md` | 建排程；每週執行時查各步驟的 Chrome 操作細節 |
| `references/metrics.md` | 數字對不上、要解釋口徑、判斷是不是月報週 |
| `references/haveababy_analysis.md` | 月報週寫 Haveababy 建議 |
