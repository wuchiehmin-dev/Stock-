# Phase 3 設計文件 · 美股 / 韓股 / 日股真實資料管線

> 本文件是「US/KR/JP 接真實資料」的實作藍圖。台股（Phase 2）已上線；美韓日尚未接真資料，
> 目前前端為寫死樣板（`index.html` 的 `MK.US/KR/JP`、`MFLOW`）。本文件把該工程拆成可執行階段。
> 資料源比較與台股主題→成分股草稿見 `Phase2_資料源與主題對照.md`。

---

## 為什麼分階段

真實市場資料需要第三方 API key，而免費額度都很小；台股那種「官方、免費、免金鑰、
一次抓全市場」的等級在美韓日並不存在。因此策略是：**只抓主題對照表裡的成分股、盤後一次更新、
把額度用在刀口上**，並把「不需 key 的架構重構」與「需 key 的接資料」分開，先鋪路再通電。

---

## 目標架構（與台股對齊）

台股目前的資料流是「後端 `fetch_data.py` → `data.json`（schema：`heatmap` / `themes` /
`stock_chg` / `index` / `insti_total` …）→ 前端讀 `data.json` 直接 render」。
美韓日沿用**同一份 schema**，只是各市場一份檔：

```
master_us.json / master_kr.json / master_jp.json   (主題 → 成分股，人工維護的情報資產)
        │  各市場盤後 workflow（分開的 cron）
        ▼
fetch（Alpha Vantage / Twelve Data，只抓對照表內成分股）
        │  加權算主題漲跌、量能
        ▼
data_us.json / data_kr.json / data_jp.json   (schema 同 data.json)
        │
        ▼
index.html 切市場 → fetch data_<market>.json；有檔=真實、無檔=「建置中」
```

schema 對齊的好處：前端 render（熱力圖、資金流向、法人維度）幾乎不用改，只要把
「切市場讀寫死 `MK`/`MFLOW`」換成「切市場 fetch `data_<market>.json`」。

---

## 階段 A — 架構鋪路（**已完成** ✅）

目標：讓前端與後端都「多市場就緒」，但先不接真資料。
（已實作：後端 `MARKET_TW` 設定＋`mkt` 參數貫穿；前端 `window.LIVE` 快取＋
`loadLive()` lazy 載入 `data_<market>.json`、render 路徑一般化、
不支援的維度按鈕 disable。之後接美股只需照下面階段 B 做。）

1. **前端切換來源**（`index.html`）
   - 現況：`renderHeatmap`/`renderFlow` 在 `cur!=="TW"` 時讀寫死的 `MK[cur]`/`MFLOW[cur]`。
   - 改成：切到某市場時 `fetch("data_"+cur.toLowerCase()+".json")`，成功則存入
     `window.LIVE_<MK>` 並比照台股 render；失敗（檔不存在）則維持「建置中」樣板狀態。
   - `marketLive(k)`（已於本次新增於 `index.html`）擴充為讀各市場的 LIVE 物件，
     header/footer 的「真實資料 vs 建置中」狀態即自動正確。
   - 非 TW 市場的「依題材／法人買賣超」維度按鈕：接上真資料的市場自動生效，
     未接的維持動能維度（不再是死按鈕）。
2. **後端多市場抽象化**（`fetch_data.py`）
   - 把台股專用的抓取／加權邏輯抽成可帶市場參數的模組，或新增
     `fetch_data_us.py` / `_kr.py` / `_jp.py` 共用同一套「主題加權 → 產 data_*.json」流程。
3. 此階段產物：前端具備多市場載入能力、後端具備多市場產檔骨架，尚無真資料。

## 階段 B — 美股接真資料（**需 key + 定稿成分股表**）

1. **申請 Alpha Vantage API key**（免費，約 25 次/日、5 次/分）。
2. **定稿 `master_us.json`**：以 `Phase2_資料源與主題對照.md` 為底，人工審閱美股極細主題→成分股
   （總量控制在約 40–50 檔，配合每日 1 次更新才在額度內）。
3. **設 GitHub Secrets**：`Settings → Secrets and variables → Actions` 新增 `ALPHAVANTAGE_KEY`，
   workflow 內以 `${{ secrets.ALPHAVANTAGE_KEY }}` 讀取（**key 絕不寫進公開 repo**）。
4. **新增 `update-data-us.yml`**：cron 設在美股收盤後（對台灣約隔天清晨），
   跑美股 fetch 產 `data_us.json` 並 commit；沿用台股 workflow 的 rebase-retry push loop。
5. 端到端驗證：確認免費額度內可穩定跑完、`data_us.json` schema 與台股一致、前端切美股顯示真資料。

## 階段 C — 韓股 / 日股（照 B 的模式複製）

1. **Twelve Data API key**（免費約 800 次/日，涵蓋日韓，盤後延遲可接受）。
2. 定稿 `master_kr.json` / `master_jp.json`，設 `TWELVEDATA_KEY` Secret。
3. 新增 `update-data-kr.yml` / `update-data-jp.yml`，cron 各設在該市場收盤後
   （日韓時區接近台灣）。

---

## 待你決定 / 提供的前置

- **API key**：階段 B/C 需要你申請並提供（或授權我引導你設 GitHub Secrets）。
- **成分股對照表定稿**：`Phase2` 內的成分股仍是草稿（多處標 (?)），這份是你的情報資產，
  需你以產業知識審閱後才建各市場 `master_*.json`。
- **是否先做階段 A**：階段 A 不需 key、純架構重構，可先行；接資料（B/C）待前兩項就緒再做。

---

## 附：本文件範圍外的更後段議題

- **真實市值**：四市場熱力圖面積目前皆以成交金額近似（`fetch_data.py` 有註記），
  真實市值需另接付費源。
- **供應鏈／關係圖真實化**：跨國供應鏈 `CHAINS`（`index.html`）為人工策展，缺真實漲跌時
  以「公司名 hash 偽隨機值」填充；低成本改善是先把偽隨機改為明確「無資料」呈現。
