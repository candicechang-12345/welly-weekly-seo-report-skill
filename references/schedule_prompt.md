# 排程提示範本與每週步驟細節

這份檔有兩個用途：
1. 「貼到排程的提示」那段，給同事貼到 Claude 桌面版的排程。
2. 「步驟細節」那段，是每週執行時要照做的完整步驟（排程和手動說「跑本週數據報告」都讀這裡）。

## 怎麼建排程

正常情況由 Claude 代建：操作者說「設定週報排程」，照 SKILL.md 初始化第 7 步用排程工具建立。下面是沒有排程工具時的手動做法，內容相同。

- Claude 桌面版左側「排程」→ 新增任務。
- 名稱：【每週四】Welly 數據週報自動填表
- 時間：每週四 09:00（cron `0 9 * * 4`，本機時間）。電腦沒開或 Claude 沒開時，下次打開 Claude 會補跑。
- 提示：貼下面整段，把 `<工作資料夾>` 換成自己電腦上的完整路徑（例如 `C:\Users\<你的帳號>\welly-weekly-seo-report`）。
- 多台電腦都建排程也不會重複填：每次開頭會先看雲端硬碟的「週報執行紀錄」。

## 貼到排程的提示

```
你是 Welly 內部 SEO 數據週報的自動填表助手。用繁體中文回報。

使用 welly-weekly-seo-report 技能跑本週數據報告。
工作資料夾：<工作資料夾>
Python 一律用 <工作資料夾>\.venv\Scripts\python，執行時設 PYTHONIOENCODING=utf-8，工作目錄設在 <工作資料夾>\scripts。

開始前：
1. 讀技能的 SKILL.md 與 references/schedule_prompt.md 的「步驟細節」，照步驟 0～7 做。
2. 把技能資料夾 scripts\ 裡的檔案複製到 <工作資料夾>\scripts\ 蓋掉舊版（<工作資料夾> 裡有 .git 就不要蓋）。
3. 找不到技能或工作資料夾時不要自己猜路徑，直接回報「技能還沒安裝或還沒初始化」並結束。

不輸入任何密碼或驗證碼，不自己發 Slack，遇到機器人驗證就停。
結尾照技能的三段格式：已完成、需要你手動補上、Slack 訊息草稿。
```

## 步驟細節

以下「工作資料夾」指操作者電腦上的副本，指令的工作目錄都是 `工作資料夾\scripts`。

### 絕對規則

- 不寫 Google 試算表，只有兩個例外：run_log.py 寫「週報執行紀錄」、article_list.py 寫「1-Welly文章與數據列表」與「HK Welly 文章與數據列表」（步驟 5.6）。其他一律只讀（「全品項數據週報」「4.1-月累NP比較流量」都只讀）。數據由 `doc_data_table.py` 整理成彩色表格插進新報告文件。唯一例外是 `run_log.py` 自己建立的「週報執行紀錄」。
- 其他雲端文件一律只讀。`copy_weekly_doc.py` 只會建立並修改它自己複製出來的新報告文件；`draft_analysis.py` 只會改那份新文件的【HaveABaby】段落；`draft_welly.py` 只會改那份新文件的【Welly】【Welly HK】段落。律所段落不動。
- 不修改同事過去填的資料。腳本會拒絕 2026-10-26 以前的期間，不要繞過。
- 不輸入任何密碼或驗證碼。Chrome 需要登入時就停下，在最後的總結請負責人處理。
- 不用 SyncWith：GA4 四格與月累由 `doc_data_table.py` 用 GA4 API 算，不要打開 SyncWith 側邊欄。
- 不自己發 Slack。

### 步驟

0. **先判斷別台電腦跑過沒**：執行 `python run_log.py check`（讀雲端硬碟的「週報執行紀錄」試算表）。結束碼 2（本週已完成或別台正在跑）→ 把輸出原文當總結，直接結束，什麼都不要做。結束碼 0 → 執行 `python run_log.py start`（登記「填表中」、電腦名稱與負責人），再往下做。
1. 執行 `python weekly_plan.py`，從輸出確認：報告區間（上週一～上週日）、本週品牌（Welly 每週；報告週包含某月最後一天時加做 WellyHK、Haveababy 該月月報）。
2. 執行 `python copy_weekly_doc.py`：複製上週報告文件、改檔名與我們品牌的標題日期。若顯示「已存在」代表已做過，繼續下一步。記下新文件連結。
3. 用 Claude in Chrome 讀 GSC 介面（API 拿不到）。使用有登入 welly.seo.team 的 Chrome（list_connected_browsers 列出後，選能打開下列網址、沒有出現「沒有存取這項資源的權限」的那個）。welly.seo.team 是這台 Chrome 的第幾個帳號每台電腦不同：先執行 `python local_config.py show` 看 gsc_user（以下用 N 表示），GSC 網址一律用 `https://search.google.com/u/N/search-console/...`；若顯示沒有權限，依序改試 /u/0/、/u/1/、/u/2/，找到能開的就執行 `python local_config.py set gsc_user <數字>` 存起來，之後的步驟與下週都用它。每個本週品牌（welly.tw、Welly TW 新站 wellyblog.tw（每週）、welly.hk、haveababy.tw）各讀三頁，用 get_page_text 或 find 讀文字，不需要截圖。新站是網址前置字元資源，下面網址的 `sc-domain%3A<網域>` 要換成 `https%3A%2F%2Fwellyblog.tw%2F`：
   - 網站使用體驗核心指標 `https://search.google.com/u/N/search-console/core-web-vitals?resource_id=sc-domain%3A<網域>`：行動裝置與桌面都是「0 個網址不良、0 個網址需要改善」→「良好」；只有行動裝置有不良或需要改善 →「行動裝置需優化」；只有桌面有 →「桌面需優化」；兩者都有 →「需優化」；顯示使用資料不足 →「資料不足」。
   - 連結 `https://search.google.com/u/N/search-console/links?resource_id=sc-domain%3A<網域>`：外部連結的「連結總數」→ links。
   - 最常連結的網站 `https://search.google.com/u/N/search-console/links/drilldown?resource_id=sc-domain%3A<網域>&type=DOMAIN&target=&domain=`：頁面底部「共 N 列」的 N → domains（GSC 最多顯示 1000 列，照實填）。

   讀完關閉你開的分頁。
4. DR／UR（新站 wellyblog.tw 也要查）：執行 `python ahrefs_api.py dr-ur --date <報告區間最後一天> <本週各網域>`（Ahrefs API key 存在 `%USERPROFILE%\.welly-seo\ahrefs.env`；不要用 Ahrefs MCP 連接器）。某站 dr 或 ur 是 null（有 error 就是額度不足或 key 失效），改用同一個 Chrome 開 `https://app.ahrefs.com/v2-site-explorer/overview?mode=subdomains&target=<網域>` 讀 DR 與 UR；仍拿不到就留空，在回報中列為待人工。
5. 數據表格（插進第 2 步的新報告文件；每個品牌先加 `--dry-run` 看輸出合理再正式跑）：
   - Welly：`python doc_data_table.py Welly --week <報告週一 YYYY-MM-DD> --doc <新文件ID> --cwv <值> --links <值> --domains <值> [--dr <值> --ur <值>]`
   - Welly 新站（每週）：`python doc_data_table.py WellyNew --week <報告週一> --doc <新文件ID> ...`（同樣參數；表格接在 Welly 表後面；新站流量小，GA4 某天 0 工作階段不會出警告）
   - 月報週再加：`python doc_data_table.py WellyHK --week <報告週一> --month <YYYY-MM> --doc <新文件ID> ...` 與 `python doc_data_table.py Haveababy --week <報告週一> --month <YYYY-MM> --doc <新文件ID> ...`
   - 表格包含 GA4 四格、GSC 四項、良好網站比例、DR／UR、外鏈域名／數量、月累，本期／上期／變化三欄，取代段落裡舊的試算表截圖（GSC 指標卡片截圖不動）。上期人工項目自動讀上週那張表；沒給的本期人工項目留空。輸出有「WARNING GA4 缺資料日期」代表 GA4 資料還沒進來，過一陣子再跑一次（重跑會原地換新表格）。
   - 記下輸出中所有「DOMAINS_CHANGED」行與「人工待填」項目。

5.2 **GSC 彩色指標卡片截圖（每個本週品牌一張，放在該品牌表格正上方）**：在第 5 步之後做。
   - a. `python weekly_plan.py --cards` 印出各品牌整站卡片網址（已套好國家、本期 vs 上期比較、local_config 的 GSC 帳號）。
   - b. 每個品牌：用同一個 Chrome 開網址，等 5 秒。左側主選單是展開的就用 find 找「主選單」按鈕點一下收起（不收起第四張「平均排序」卡會被切掉）。
   - c. 用 javascript_tool 量卡片範圍：
     ```js
     const f=t=>[...document.querySelectorAll('div,span')].filter(e=>e.childElementCount===0&&e.textContent.trim()===t&&e.offsetParent)[0];const a=f('總點擊次數'),b=f('平均排序');let n=a;while(n&&!n.contains(b))n=n.parentElement;const c=[...n.children].map(x=>x.getBoundingClientRect());JSON.stringify({x:c[0].x,y:c[0].y,right:c[c.length-1].right,bottom:c[0].bottom,vw:innerWidth})
     ```
     x 要小於 100（選單已收起；選單展開時 x 約 300，第四張卡會被內容區切掉，就算 right 小於 vw 也一樣），否則回到 b。
   - d. 先 computer screenshot（scale 0.5）拿到座標框架寬度 W（輸出的「coordinate frame: W x H」），比例 k＝W／vw。用 computer zoom，region＝[x·k, y·k, right·k, bottom·k]（四捨五入），save_to_disk: true，記下存檔路徑。看一下圖：要剛好是四張彩色卡片、不含圖表和選單，日期要是本期 vs 上期。
   - e. `python doc_gsc_card.py <品牌> --week <報告週一> --doc <新文件ID> --image <存檔路徑>`（品牌：Welly、WellyNew、月報週加 WellyHK、Haveababy）。程式會換掉上週留下的卡片圖，重跑也只會換掉不會多一張。
   - f. 截圖一直逾時（Chrome 視窗被縮小或擋住）或量不到卡片，就跳過該品牌，回報「⚠ <品牌> GSC 卡片截圖沒做成，請手動截圖換掉文件裡上週的舊圖」，並附 a 的網址。做完關閉你開的分頁。

5.4 **Welly（月報週含 Welly HK）文字草稿（每週）**：在第 5 步之後做，寫進第 2 步的新報告文件。句型照過去報告，數字由腳本從 GSC API 算，你只要查大字排名。
   - a. 查大字「SEO」「SEO公司」：用同一個 Chrome 依序開 `https://www.google.com/search?q=<字>&hl=zh-TW&gl=tw&pws=0&start=<0,10,20,30,40>`（前五頁，舊站 welly.tw 和新站 wellyblog.tw 都找到或翻完五頁就停），用 javascript_tool 讀 `#search a h3` 的網址。第 1 頁另外看頁面上方有沒有「AI 摘要」，以及 #search 以外有沒有連到 welly.tw、wellyblog.tw 的連結（＝有出現在 AIO）。出現機器人驗證（CAPTCHA）就停，不要嘗試通過，該字不寫 rank。
   - b. 寫成 notes.json，存在 `工作資料夾\drafts\<報告週一>_Welly_notes.json`：`{"serp_source": "Chrome（pws=0）<M/D>", "serp": {"SEO": {"rank": "無痕第三頁", "aio": false, "target_page": true}, "SEO公司": {...}}}`。rank 照過去寫法：第 1 頁寫「無痕第 N 名」，其他頁寫「無痕第二頁」「無痕第三頁」（國字），前五頁都沒有寫「沒有出現在無痕前五頁」；搜到的不是主攻頁（SEO → /blog/what-is-seo、SEO公司 → /blog/how-to-choose-seo-agency）就把 target_page 設成 false。新站 wellyblog.tw 用同樣寫法另外放在 `"serp_new": {"SEO": {"rank": ..., "aio": ...}, "SEO公司": {...}}`（新站不用 target_page）。
   - c. 先 `python draft_welly.py write --week <報告週一> --doc <新文件ID> --notes <notes.json> --dry-run` 看草稿，合理再拿掉 `--dry-run` 正式寫入。月報週腳本會自動一起寫【Welly HK】。Welly TW 轉移到 wellyblog.tw 期間，【Welly】段落會分【舊站】【新站】兩個小標，各自列整站與大字（新站數字腳本自己從 GSC／GA4 抓，版面寫在程式裡，不用手動調）。顯示「已經有 Claude 草稿」代表已寫過（負責人可能改過），不要加 `--force`，直接略過。

5.6 **文章與數據列表（Welly TW 每週、Welly HK 只在月報週；2026-11-26 起自動）**：在 5.4 之後做。下面寫 TW 的指令，月報週（weekly_plan.py 有列 WellyHK 的那週）把 TW 換成 HK 再做一輪，兩份互不影響，一份有問題不要擋另一份。非月報週不要跑 HK。
   a. `python article_list.py check TW`。輸出「本期已經貼過了」而且沒有標「問題」的項目 → 這一步完成，略過 b、c。
   b. 有標「問題」而且是 #REF!（G 欄出錯）→ **不要寫入，也不要去刪 GSCdata 的列**。把輸出裡「建議刪除這一列」的每一行（GSCdata 列號、query、page）原樣記下來，放進最後的「需要你手動補上」：「文章與數據列表有 #REF!，請到 GSCdata 分頁刪掉下列各列，刪完跟 Claude 說『補跑文章與數據列表』」，並附試算表連結（weekly_plan.py 的 ARTICLE_LISTS）。
   c. 沒有 #REF!：先 `python article_list.py run TW --dry-run` 看計畫合理，再 `python article_list.py run TW --allow-original` 正式寫入（會先備份到 專案\drafts，寫完自己讀回驗證）。讀回驗證有任何一項不是「通過」，就把輸出原文放進回報並列為待人工，不要重跑。
   d. 使用者之後說「補跑文章與數據列表」時：重做 a。本期還沒貼就做 c；本期已貼但歷史欄有 #REF! 被貼進去，改跑 `python article_list.py repair TW --dry-run` 再 `python article_list.py repair TW --allow-original`。
   e. 這支程式只准用在 TW、HK 這兩份文章與數據列表，`--allow-original` 不要用在其他指令或其他檔案。回報時 TW、HK 分開寫結果。
5.5 **Haveababy 分析草稿（只有月報週，也就是 weekly_plan.py 有列 Haveababy 的那週）**：在第 5 步填完 Haveababy 之後做，寫進第 2 步的新報告文件（文件 ID 從連結取）。只能寫這份文件的【HaveABaby】段落，腳本會擋其他文件和其他段落。
   - a. `python draft_analysis.py collect --month <YYYY-MM>`：抓 GSC／GA4／數據週報、上一份週報裡的上月建議，印出要查 SERP 的字和要改的文章。若有「GSC 資料只到…」警告，代表月底資料還沒進來，照樣做，回報時註明。collect 會順便用 DataForSEO 查搜尋熱度（帳密在 `%USERPROFILE%\.welly-seo\dataforseo.env`），結果寫在灰字；有「DataForSEO 搜尋熱度沒抓到」警告就照樣做，回報時註明。
   - b. 查 SERP（每個字）：先用 `python ahrefs_api.py serp --country tw <字1> <字2> …`（results 是自然結果，aio 是否有 AI 摘要）；有 error（額度不足）就用同一個 Chrome 開 `https://www.google.com/search?q=<字>&hl=zh-TW&gl=tw&pws=0`，用 javascript_tool 讀 `#search a h3` 的標題與網址、頁面上方有沒有「AI 摘要」、haveababy.tw 排第幾。出現機器人驗證（CAPTCHA）就停，不要嘗試通過，該字留空。
   - c. 每篇要改的文章：`python draft_analysis.py outline <我們的文章> <SERP 前 2～3 名的文章>`，比較 H1／H2／H3、FAQ、FAQPage schema，找出 HaveABaby 缺的段落與搜尋意圖落差。
   - d. 把結果寫成 notes.json（格式見 `draft_analysis.py` 開頭說明，存在 `工作資料夾\drafts\<YYYY-MM>_Haveababy_notes.json`）：`serp_source`（例如「Chrome 無痕 11/5」）、`serp`（rank 照過去報告寫法，例如「無痕第 3 名」「掉出無痕首頁」「無痕第二頁」；aio 是否出現）、`targets`（每篇的 intent、suggestions、evidence）。suggestions 的方向依 collect 印出的「判讀」決定，對照 `references/haveababy_analysis.md` 第三、四節。suggestions 是給客戶看的黑字，照過去報告的短句寫法：「H1 標題：往…方向調整。」「新增內容：在「…」前新增 H2 段落 →「…」。」「新增 FAQ 段落，並建立 schema。」「新增文章：…，並互相內鏈。」（另可用「標題與描述：往…方向調整。」「前言：…」），每篇 2～4 點，不要在黑字裡解釋原因；SERP 看到的證據（競品有什麼、我們缺什麼）寫進 evidence，會變成灰字給負責人檢查。建議寫到單篇文章架構；上月建議腳本會自動原樣複製並加灰字說明，不用自己寫。文字不用破折號、不用空話。查不到的不要編，留給草稿標【待確認】。
   - e. 先 `python draft_analysis.py write --month <YYYY-MM> --doc <新文件ID> --notes <notes.json> --dry-run` 看草稿，合理再拿掉 `--dry-run` 正式寫入。若顯示「已經有 Claude 草稿」代表已寫過（負責人可能改過），不要加 `--force`，直接略過。

6. **回報存到執行紀錄**：把下列內容寫成 Markdown 存到暫存檔，主要步驟都成功就執行 `python run_log.py done --body-file <檔案> --doc <新報告文件連結>`（執行紀錄改成「已完成」並存回報）；複製文件或填表失敗就執行 `python run_log.py fail --body-file <檔案>`（改成「未完成」，下次可重跑）。內容：
   - 新報告文件連結
   - 每個品牌已填入的 GA4 四格、月累、GSC 點擊／曝光／點閱率／排序、良好網站比例、外鏈數量、外鏈域名、DR／UR
   - 若有 DOMAINS_CHANGED：寫「⚠ <品牌> 外鏈域名 <舊> → <新>，請更新外鏈域名紀錄」並附該品牌外鏈域名紀錄連結（在 `weekly_plan.py` 的 DOMAIN_LOGS）
   - Welly 的數字分【舊站】（Welly 區塊）與【新站】（WellyNew 區塊，wellyblog.tw）兩組列出
   - 各品牌 GSC 卡片截圖是否已插入；沒做成的照 5.2 f 寫
   - 「Welly 文字草稿已寫入（月報週含 Welly HK），請檢查後再發到 Slack」；有略過或沒寫成就寫原因
   - 月報週：「Haveababy 分析草稿已寫入，請檢查數據、依據與結論後再發到 Slack」＋新報告文件連結；草稿沒寫成就寫原因
   - 還沒做到的項目（例如 DR／UR 拿不到、Chrome 需要登入）
   - 若有 GA4 缺資料警告，寫「⚠ GA4 缺資料：<日期>，請稍後請 Claude 重跑填表」
7. **最後在對話裡給負責人看的總結**（負責人可能是代班同事，寫清楚、不要用程式名稱），分三段。任何步驟失敗不要硬做，記錄原因後繼續其他步驟。
   - a. **已完成**：三五句話說做了什麼，附新報告文件連結。
   - b. **需要你手動補上**：打勾清單。先列這次沒做成的（卡片截圖、DR／UR、【待確認】的無痕排名、GA4 缺資料要重跑等，附連結），再列每週固定的人工項目：執行 `python weekly_plan.py`，把輸出中各品牌「其他人工項目」裡沒有標「（自動，排程沒跑到再手動）」的項目照抄，標「自動」的只列這次沒抓到的。月報週要寫「檢查 Haveababy 分析草稿，刪掉灰字後發到 Slack」。
   - c. **Slack 訊息草稿**：不要自己發 Slack。照下面的公版寫好可以直接複製的訊息，請負責人檢查完報告後手動貼到頻道（2026-11-26 起不需要主管審核）。公版的字句、符號、表情代碼都照抄，只換日期、月份與連結；連結用 Slack 貼上後會變成連結的寫法（文字後面接網址），並提醒負責人貼上後把那段文字設成連結。
      - 每週，貼到 #seo內部案專用頻道：`:公告:<MM/DD>~<MM/DD> 內部數據分析報告 Welly  的部分完成～再麻煩了！:barbapapapink:`。日期是報告區間的週一與週日，月日各兩位數（例：11/09~11/15）；「<MM/DD>~<MM/DD> 內部數據分析報告」這段要連到本週報告文件。
      - 月報週另外一則，貼到 #haveababy文章討論區：`嗨嗨 @李佳軒 這是 <N> 月底整體數據報告，可以再參考文檔中提供的優化建議～感謝:ditto_sparkle_party_dance:`。N 是月報的月份；「<N> 月底整體數據報告」這段要連到本週報告文件；@李佳軒 要請負責人在 Slack 裡重新選一次才會真的提及到人。
