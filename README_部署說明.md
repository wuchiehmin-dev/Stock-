# 台股熱力圖 · Phase 2 部署說明（給完全新手）

這份說明帶你把儀表板變成「每天自動更新台股真實資料」的線上網站。
全程免費、不用租伺服器、不用寫程式。跟著步驟做即可。

你會用到三個檔案：
- `index.html`　網頁本體（已改成會自動讀 `data.json`）
- `fetch_data.py`　抓證交所資料、產生 `data.json` 的腳本
- `update-data.yml`　讓 GitHub 每天自動跑腳本的排程設定

---

## 先理解整個流程（一分鐘）

```
GitHub Actions（雲端排程，每個交易日下午自動觸發）
        │
        ▼
執行 fetch_data.py ── 連證交所抓當日全上市個股量價 + 產業別
        │
        ▼
算出各板塊市值加權漲跌 → 產生 data.json → 自動 commit 回 repo
        │
        ▼
GitHub Pages 上的 index.html 讀到新的 data.json → 熱力圖顯示今日真實盤面
```

重點：**抓資料在 GitHub 的雲端跑，不是在你的電腦跑**。你電腦關機也會更新。

---

## 步驟一：建立 GitHub repo（5 分鐘）

1. 到 https://github.com 註冊 / 登入（你已有帳號 wuchiehmin-dev）。
2. 右上角「＋」→「New repository」。
3. Repository name 填例如 `sector-dashboard`，選 **Public**（公開，GitHub Pages 免費版需要）。
4. 勾選「Add a README file」，按「Create repository」。

## 步驟二：上傳三個檔案（5 分鐘）

1. 在 repo 頁面按「Add file」→「Upload files」。
2. 把 `index.html`、`fetch_data.py` 拖進去上傳，按「Commit changes」。
3. `update-data.yml` 要放在特定資料夾：再按「Add file」→「Create new file」，
   檔名欄位輸入 `.github/workflows/update-data.yml`（輸入斜線會自動建資料夾），
   把 `update-data.yml` 的內容貼進去，按「Commit changes」。

上傳後 repo 結構應該長這樣：
```
sector-dashboard/
├── index.html
├── fetch_data.py
└── .github/
    └── workflows/
        └── update-data.yml
```

## 步驟三：開啟 GitHub Pages（2 分鐘）

1. repo 頁面上方「Settings」→ 左側「Pages」。
2. 「Source」選「Deploy from a branch」，Branch 選 `main`、資料夾選 `/ (root)`，按 Save。
3. 等一兩分鐘，頁面上方會出現你的網址：
   `https://wuchiemin-dev.github.io/sector-dashboard/`
   （用你的帳號名，實際網址以頁面顯示為準）
4. 打開這個網址，先看到的是樣板資料（因為 data.json 還沒產生）。

## 步驟四：第一次手動觸發，產生真實資料（3 分鐘）

1. repo 頁面上方「Actions」分頁。
2. 左側點「更新台股熱力圖資料」，右邊按「Run workflow」→「Run workflow」綠色鈕。
3. 等約 1 分鐘，跑完會出現綠色勾勾，repo 裡就多了一個 `data.json`。
4. 重新整理你的 GitHub Pages 網址 —— 熱力圖現在是**今日真實台股盤面**了！
   （標題會顯示「台股熱力圖真實資料 · 更新 時間」）

> 注意：如果當天是假日或還沒收盤，`STOCK_DAY_ALL` 可能沒資料，
> 腳本會跳過、不覆蓋舊檔。平日 15:00 後再跑就有。

## 步驟五：確認自動排程已生效

`update-data.yml` 已設定每個交易日（週一到週五）台灣時間約 15:00 與 17:00
各自動跑一次。你什麼都不用做，之後每天盤後熱力圖會自己更新。

---

## 常見問題

**Q：Actions 沒有自動跑？**
GitHub 對太久沒活動的 repo 會暫停排程。進 repo 隨便 commit 一次、或到 Actions 手動 Run 一次即可喚醒。

**Q：想改板塊怎麼分類？**
編輯 `fetch_data.py` 最上面的 `INDUSTRY_MAP`，把證交所產業別對應到你要的板塊名稱。

**Q：熱力圖面積代表什麼？**
目前用「當日成交金額（收盤×成交股數）」當面積的近似，不是真實市值。
證交所免費資料沒有即時市值，要真實市值需另接（例如 FinMind 或付費源），列為之後的加值項。

**Q：其他區塊（資金流向、供應鏈、關係圖）還是樣板？**
是的。這一階段只先接「台股熱力圖」的真實資料，其餘維持樣板。
下一步可依序接：台股資金流向極細主題（需維護主題→成分股對照表）、再擴到美韓日。

---

## 自動化報告分頁（每日新聞匯總 / 每週焦點報告）

網站右上多了一個「📰 報告」分頁，會列出 `reports/` 資料夾裡的 Markdown 報告。
資料流：

```
你電腦上的 Claude 自動排程（產出每日/每週報告）
        │  存檔 + git push
        ▼
repo 的 reports/daily/YYYY-MM-DD.md 或 reports/weekly/YYYY-MM-DD.md
        │  GitHub Actions 自動重建 reports/index.json
        ▼
GitHub Pages「報告」分頁自動列出、點選即可閱讀
```

### 檔案慣例

- 每日新聞匯總 → `reports/daily/YYYY-MM-DD.md`
- 每週焦點報告 → `reports/weekly/YYYY-MM-DD.md`（建議用該週最後一個交易日命名）
- 第一行寫 `# 標題`，清單會顯示這個標題
- `reports/index.json` 不用手動維護，push 後 Actions 會自動重建

### 本機排程要改什麼

前提：你的電腦有這個 repo 的 clone 且能 push（`git clone` 過並登入 GitHub）。
在你既有的排程任務指示最後，加上類似這段：

> 報告完成後，把內容存成 Markdown 到本機的 Stock- repo：
> 每日報告存 `reports/daily/今天日期.md`、每週報告存 `reports/weekly/日期.md`，
> 第一行為 `# 報告標題`。然後執行：
> `git pull --rebase origin main`，`git add reports`，
> `git commit -m "新增報告"`，`git push origin main`。

推上去約 1-2 分鐘後，網站重新整理就看得到。
`reports/` 裡目前有兩篇範例報告示範格式，流程跑通後可刪除。

---

## 這一階段完成了什麼

- [x] 台股熱力圖顯示每個交易日的真實盤後資料
- [x] GitHub Actions 全自動更新，零維護
- [x] 免費、無伺服器、公開網址可分享
- [x] 資金流向極細主題接真資料（master_tw.json × 證交所量價，週/月動能由 history_tw.json 累積）
- [x] 三大法人買賣超（上市 T86 + 上櫃 dailyTrade，主題聚合日/週/月，資金流向區「法人買賣超」維度）
- [ ] 美股 / 韓股 / 日股（再下一步，資料源不同）
