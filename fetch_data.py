#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 2 · 台股熱力圖資料抓取
--------------------------------
從臺灣證券交易所公開資料抓取「當日全上市個股成交」與「上市公司產業別」，
按產業別彙總成市值加權漲跌，輸出 data.json 供前端熱力圖讀取。

資料來源（皆為證交所公開資料，免金鑰）：
  1. 個股當日成交： https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=json
  2. 上市公司產業別： https://mopsfin.twse.com.tw/opendata/t187ap03_L.csv

注意：
  - 這支腳本要在「能連到證交所」的環境跑（你的電腦 / GitHub Actions），
    Claude 的沙盒連不到證交所，所以無法在對話中直接幫你跑出結果。
  - 證交所有流量限制，本腳本只打 2 個 request，不會觸發。
  - 非交易日（假日）STOCK_DAY_ALL 可能回空，腳本會保留上一次的 data.json。
"""

import json
import csv
import io
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))  # 台北時間
UA = {"User-Agent": "Mozilla/5.0 (compatible; SectorDashboard/1.0)"}

STOCK_DAY_ALL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=json"
COMPANY_LIST = "https://mopsfin.twse.com.tw/opendata/t187ap03_L.csv"
# 可指定日期、一次抓全部個股當日成交（用於假日回補最近交易日）
MI_INDEX = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&type=ALLBUT0999&date={date}"
# 市場成交資訊（含每日加權指數收盤與漲跌點數），date 給該月任一天即回整月
FMTQIK = "https://www.twse.com.tw/exchangeReport/FMTQIK?response=json&date={date}"

# 櫃買中心（上櫃）資料源，皆免金鑰
COMPANY_LIST_OTC = "https://mopsfin.twse.com.tw/opendata/t187ap03_O.csv"  # 上櫃公司產業別
TPEX_DAILY = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"  # 最新交易日全上櫃收盤
TPEX_DAILY_BY_DATE = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={roc}&response=json"  # 指定日期回補

# 證交所產業別「代碼」→ 名稱（t187ap03_L.csv 的產業別欄位給的是代碼）
INDUSTRY_CODE2NAME = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維",
    "05": "電機機械", "06": "電器電纜", "08": "玻璃陶瓷", "09": "造紙工業",
    "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業", "14": "建材營造業",
    "15": "航運業", "16": "觀光餐旅", "17": "金融保險業", "18": "貿易百貨業",
    "19": "綜合", "20": "其他業", "21": "化學工業", "22": "生技醫療業",
    "23": "油電燃氣業", "24": "半導體業", "25": "電腦及週邊設備業",
    "26": "光電業", "27": "通信網路業", "28": "電子零組件業",
    "29": "電子通路業", "30": "資訊服務業", "31": "其他電子業",
    "32": "文化創意業", "33": "農業科技業", "34": "電子商務",
    "35": "綠能環保", "36": "數位雲端", "37": "運動休閒", "38": "居家生活",
    "80": "管理股票", "91": "存託憑證",
}

# 證交所產業別 → 儀表板顯示板塊（可自行調整合併）
INDUSTRY_MAP = {
    "半導體業": "半導體",
    "電腦及週邊設備業": "電腦及週邊",
    "光電業": "光電",
    "通信網路業": "通信網路",
    "電子零組件業": "電子零組件",
    "電子通路業": "電子通路",
    "資訊服務業": "資訊服務",
    "其他電子業": "其他電子",
    "金融保險業": "金融",
    "航運業": "航運",
    "鋼鐵工業": "鋼鐵",
    "塑膠工業": "塑膠",
    "食品工業": "食品",
    "汽車工業": "汽車",
    "生技醫療業": "生技醫療",
    "電機機械": "電機機械",
    "建材營造業": "建材營造",
    "紡織纖維": "紡織",
    "橡膠工業": "橡膠",
    "水泥工業": "水泥",
    "油電燃氣業": "油電燃氣",
    "貿易百貨業": "貿易百貨",
    "觀光餐旅": "觀光餐旅",
    "玻璃陶瓷": "玻璃陶瓷",
    "造紙工業": "造紙",
    "化學工業": "化學",
    "電器電纜": "電器電纜",
}


def fetch_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_csv(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(raw)))


def to_float(s):
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    if s in ("", "--", "N/A", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def build_industry_lookup():
    """回傳 {股票代號: 產業別} 對照（上市 + 上櫃）。"""
    rows = fetch_csv(COMPANY_LIST)
    try:
        time.sleep(2)  # 禮貌間隔
        rows += fetch_csv(COMPANY_LIST_OTC)
    except Exception as e:
        print(f"  上櫃產業別抓取失敗（僅用上市，略過）：{e}")
    lookup = {}
    # 欄位名稱可能是「公司代號」「產業別」，做容錯
    for row in rows:
        code = None
        ind = None
        for k, v in row.items():
            if k and ("代號" in k or "代碼" in k) and v and v.strip().isdigit():
                code = v.strip()
            if k and "產業別" in k:
                ind = (v or "").strip()
        if code and ind:
            if ind.isdigit():  # 欄位給代碼時轉成名稱
                ind = INDUSTRY_CODE2NAME.get(ind.zfill(2), ind)
            lookup[code] = ind
    return lookup


# 最近一次 fetch_json_retry 的失敗型態：None=成功、"http"=連線/HTTP錯誤（多半是被限流）、
# "nonjson"=回傳非 JSON、"empty"=回傳空白。回補腳本靠它分辨「被限流」與「休市無資料」。
LAST_ERROR = None


def fetch_json_retry(url, label, tries=3, wait=8):
    """抓 JSON，遇到非 JSON（證交所偶爾擋雲端 IP 回 HTML）或連線失敗時重試。
    回傳 dict 或 None。"""
    global LAST_ERROR
    for attempt in range(1, tries + 1):
        req = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8").strip()
        except Exception as e:
            print(f"  {label} 連線失敗（第{attempt}次）：{e}")
            LAST_ERROR = "http"
            raw = None
        if raw:
            try:
                data = json.loads(raw)
                LAST_ERROR = None
                return data
            except ValueError:
                print(f"  {label} 回傳非 JSON（第{attempt}次），開頭：{raw[:60]!r}")
                LAST_ERROR = "nonjson"
        elif raw == "":
            print(f"  {label} 回傳空白（第{attempt}次）。")
            LAST_ERROR = "empty"
        if attempt < tries:
            time.sleep(wait)
    return None


def parse_stock_day_all_csv(raw):
    """STOCK_DAY_ALL 被限流時證交所會改回 CSV 格式（內容其實完整），直接解析。"""
    out = []
    for row in csv.DictReader(io.StringIO(raw)):
        def g(*keys):
            for k in keys:
                for rk, v in row.items():
                    if rk and k in rk:
                        return v
            return None
        code = (g("證券代號") or "").strip()
        if not (code.isdigit() and len(code) == 4):
            continue
        close = to_float(g("收盤價"))
        vol = to_float(g("成交股數"))
        if close is None or vol is None:
            continue
        change = to_float(g("漲跌價差"))
        chg_pct = None
        if change is not None and (close - change):
            chg_pct = round(change / (close - change) * 100, 2)
        out.append({"code": code, "name": (g("證券名稱") or code).strip(),
                    "close": close, "change_pct": chg_pct if chg_pct is not None else 0.0,
                    "volume": vol})
    return out


def fetch_quotes():
    """回傳 list[dict]，每檔含 code/name/close/change_pct/volume。
    非交易日（假日）證交所可能回空白或非 JSON，此時回傳 None 視為無資料。"""
    data = fetch_json_retry(STOCK_DAY_ALL, "個股成交")
    if data is None:
        # 非 JSON 時可能是被降級成 CSV（資料其實在裡面），抓原文再試一次
        if LAST_ERROR == "nonjson":
            try:
                req = urllib.request.Request(STOCK_DAY_ALL, headers=UA)
                with urllib.request.urlopen(req, timeout=30) as r:
                    raw = r.read().decode("utf-8-sig", errors="replace").strip()
                if raw and "證券代號" in raw.splitlines()[0]:
                    out = parse_stock_day_all_csv(raw)
                    if out:
                        print(f"  個股成交改以 CSV 解析成功：{len(out)} 檔")
                        return out
            except Exception as e:
                print(f"  CSV 備援解析失敗：{e}")
        return None
    if data.get("stat") != "OK" or "data" not in data:
        print(f"  個股成交 stat 非 OK：{data.get('stat')}")
        return None
    fields = data.get("fields", [])
    # 依欄位名稱定位索引，避免順序變動
    def idx(*names):
        for n in names:
            for i, f in enumerate(fields):
                if n in f:
                    return i
        return None

    i_code = idx("證券代號", "代號")
    i_name = idx("證券名稱", "名稱")
    i_vol = idx("成交股數", "成交量")
    i_close = idx("收盤價")
    i_change = idx("漲跌價差", "漲跌")
    i_open = idx("開盤價")

    out = []
    for row in data["data"]:
        try:
            code = row[i_code].strip()
        except Exception:
            continue
        if not code.isdigit() or len(code) != 4:
            continue  # 只取 4 碼一般個股
        close = to_float(row[i_close]) if i_close is not None else None
        change = to_float(row[i_change]) if i_change is not None else None
        vol = to_float(row[i_vol]) if i_vol is not None else None
        if close is None or vol is None:
            continue
        # 漲跌幅 %：用漲跌價差 / (收盤 - 漲跌價差) 反推昨收
        chg_pct = None
        if change is not None and (close - change) not in (0, None):
            prev = close - change
            if prev:
                chg_pct = round(change / prev * 100, 2)
        out.append({
            "code": code,
            "name": row[i_name].strip() if i_name is not None else code,
            "close": close,
            "change_pct": chg_pct if chg_pct is not None else 0.0,
            "volume": vol,  # 成交股數
        })
    return out


def aggregate_by_sector(quotes, industry_lookup):
    """按產業別彙總成熱力圖需要的 treemap 結構。"""
    sectors = {}
    for q in quotes:
        raw_ind = industry_lookup.get(q["code"])
        if not raw_ind:
            continue
        sector = INDUSTRY_MAP.get(raw_ind, raw_ind)
        # 用「成交金額 ≈ 收盤 × 成交股數」當市值權重的代理（無法取真實市值時的近似）
        weight = q["close"] * q["volume"] / 1e8  # 億元
        s = sectors.setdefault(sector, {"name": sector, "stocks": [], "w_sum": 0.0, "wchg_sum": 0.0})
        s["stocks"].append({
            "name": q["name"],
            "value": round(weight, 2),
            "chg": q["change_pct"],
        })
        s["w_sum"] += weight
        s["wchg_sum"] += weight * q["change_pct"]

    result = []
    for s in sectors.values():
        if s["w_sum"] <= 0:
            continue
        sector_chg = round(s["wchg_sum"] / s["w_sum"], 2)
        # 每個板塊只保留成交金額前 8 大個股，避免 treemap 太碎
        top = sorted(s["stocks"], key=lambda x: x["value"], reverse=True)[:8]
        result.append({
            "name": s["name"],
            "chg": sector_chg,
            "value": round(s["w_sum"], 1),
            "children": top,
        })
    # 板塊依成交金額由大到小
    result.sort(key=lambda x: x["value"], reverse=True)
    return result


def parse_mi_index(data):
    """解析 MI_INDEX 回傳，抽出個股 code/name/close/change_pct/volume。
    MI_INDEX 的個股表通常在 data9 / tables 之一，欄位含代號/收盤/漲跌(+-)/漲跌價差。"""
    # 新版回傳有 tables 陣列；舊版有 data1..data9。都嘗試。
    candidate_rows = []
    if isinstance(data.get("tables"), list):
        for t in data["tables"]:
            fields = t.get("fields", [])
            if any("證券代號" in f or "股票代號" in f for f in fields):
                candidate_rows.append((fields, t.get("data", [])))
    for i in range(1, 12):
        key = "data%d" % i
        fkey = "fields%d" % i
        if key in data and fkey in data:
            fields = data.get(fkey, [])
            if any("證券代號" in f or "股票代號" in f for f in fields):
                candidate_rows.append((fields, data[key]))
    if not candidate_rows:
        return None

    out = []
    for fields, rows in candidate_rows:
        def idx(*names):
            for n in names:
                for i, f in enumerate(fields):
                    if n in f:
                        return i
            return None
        i_code = idx("證券代號", "股票代號")
        i_name = idx("證券名稱", "股票名稱")
        i_close = idx("收盤價")
        i_dir = idx("漲跌(+/-)", "漲跌")
        i_diff = idx("漲跌價差")
        i_vol = idx("成交股數")
        if i_code is None or i_close is None:
            continue
        for row in rows:
            try:
                code = str(row[i_code]).strip()
            except Exception:
                continue
            if not (code.isdigit() and len(code) == 4):
                continue
            close = to_float(row[i_close])
            vol = to_float(row[i_vol]) if i_vol is not None else None
            if close is None or vol is None:
                continue
            diff = to_float(row[i_diff]) if i_diff is not None else None
            # 方向：漲跌欄可能是 HTML 的 <p>+</p> 或純 +/-
            sign = 1
            if i_dir is not None:
                dtxt = str(row[i_dir])
                if "-" in dtxt or "green" in dtxt.lower():
                    sign = -1
            chg_pct = None
            if diff is not None:
                signed_diff = diff * sign
                prev = close - signed_diff
                if prev:
                    chg_pct = round(signed_diff / prev * 100, 2)
            out.append({
                "code": code,
                "name": str(row[i_name]).strip() if i_name is not None else code,
                "close": close,
                "change_pct": chg_pct if chg_pct is not None else 0.0,
                "volume": vol,
            })
        if out:
            break
    return out or None


def fetch_quotes_by_date(yyyymmdd):
    """用 MI_INDEX 抓指定日期全市場個股。非交易日回 None。"""
    url = MI_INDEX.format(date=yyyymmdd)
    data = fetch_json_retry(url, f"MI_INDEX {yyyymmdd}", tries=2)
    if data is None:
        return None
    if data.get("stat") != "OK":
        print(f"  MI_INDEX {yyyymmdd} stat：{data.get('stat')}")
        return None
    return parse_mi_index(data)


MASTER_FILE = "master_tw.json"
HISTORY_FILE = "history_tw.json"
HISTORY_KEEP_DAYS = 45  # 保留最近 45 個交易日，足夠算月動能


def load_master_themes():
    """讀取主題主檔 master_tw.json；不存在或壞掉回傳空 list（不影響熱力圖）。"""
    try:
        with open(MASTER_FILE, encoding="utf-8") as f:
            return json.load(f).get("themes", [])
    except Exception as e:
        print(f"  ! 讀取 {MASTER_FILE} 失敗：{e}", file=sys.stderr)
        return []


def load_history():
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def compound_chg(chgs):
    """多日漲跌幅複利合成，回傳 %。"""
    acc = 1.0
    for c in chgs:
        acc *= 1 + c / 100.0
    return round((acc - 1) * 100, 2)


def compute_day_record(quotes):
    """單日主題聚合。回傳 (day_themes, day_stocks, themes_out)；主檔缺失回 (None, None, None)。
    回補歷史腳本也共用這個函式。"""
    master = load_master_themes()
    if not master:
        return None, None, None

    qmap = {q["code"]: q for q in quotes}

    # 當日：每主題加權漲跌 + 成交金額（億元）；每檔個股漲跌
    day_themes = {}
    day_stocks = {}
    themes_out = []
    for t in master:
        stocks_out = []
        w_sum = 0.0
        wchg_sum = 0.0
        for code, name in t.get("stocks", []):
            q = qmap.get(code)
            if q:
                val = round(q["close"] * q["volume"] / 1e8, 2)  # 成交金額 億元
                chg = q["change_pct"]
                w_sum += val
                wchg_sum += val * chg
                day_stocks[code] = chg
                stocks_out.append({"code": code, "name": name, "chg": chg, "value": val})
            else:
                # 上櫃或當日無成交 → 無報價，前端以 0 顯示
                stocks_out.append({"code": code, "name": name, "chg": None, "value": None})
        chg_d = round(wchg_sum / w_sum, 2) if w_sum > 0 else 0.0
        vol_d = round(w_sum, 1)
        day_themes[t["id"]] = {"chg": chg_d, "vol": vol_d}
        themes_out.append({
            "id": t["id"],
            "name": t["name"],
            "group": t.get("group"),
            "tier": t.get("tier"),
            "supplies_to": t.get("supplies_to", []),
            "chg": {"d": chg_d},
            "vol": {"d": vol_d},
            "stocks": stocks_out,
        })
    return day_themes, day_stocks, themes_out


def build_theme_payload(quotes, data_date):
    """依 master_tw.json 主題聚合真實量價，並用 history_tw.json 累積算週/月動能。
    回傳 (themes_out, stock_chg_out)；主檔缺失時回傳 (None, None)。"""
    day_themes, day_stocks, themes_out = compute_day_record(quotes)
    if themes_out is None:
        return None, None

    # 更新歷史（以 data_date 為 key，重跑同一天會覆蓋不會重複累積）
    history = load_history()
    history[data_date] = {"themes": day_themes, "stocks": day_stocks}
    dates = sorted(history.keys(), reverse=True)[:HISTORY_KEEP_DAYS]
    history = {d: history[d] for d in dates}
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False)
    print(f"  歷史資料：{len(dates)} 個交易日（{dates[-1]} ~ {dates[0]}）")

    # 週(5日)/月(21日)：漲跌複利合成、量加總（歷史不足就用現有天數）
    for th in themes_out:
        tid = th["id"]
        w_chgs, w_vol, m_chgs, m_vol = [], 0.0, [], 0.0
        for i, d in enumerate(dates):
            rec = history[d]["themes"].get(tid)
            if not rec:
                continue
            if i < 5:
                w_chgs.append(rec["chg"])
                w_vol += rec["vol"]
            if i < 21:
                m_chgs.append(rec["chg"])
                m_vol += rec["vol"]
        th["chg"]["w"] = compound_chg(w_chgs)
        th["chg"]["m"] = compound_chg(m_chgs)
        th["vol"]["w"] = round(w_vol, 1)
        th["vol"]["m"] = round(m_vol, 1)

    # 個股：日 + 週（供關係圖外框配色）
    stock_chg_out = {}
    all_codes = set()
    for d in dates[:5]:
        all_codes.update(history[d]["stocks"].keys())
    for code in all_codes:
        w_chgs = [history[d]["stocks"][code] for d in dates[:5] if code in history[d]["stocks"]]
        entry = {}
        if code in day_stocks:
            entry["d"] = day_stocks[code]
        if w_chgs:
            entry["w"] = compound_chg(w_chgs)
        if entry:
            stock_chg_out[code] = entry

    return themes_out, stock_chg_out


def _pick(row, *keys):
    """從 dict 容錯取值：key 完全相等或包含。"""
    for k in keys:
        if k in row:
            return row[k]
    for k in keys:
        for rk in row:
            if rk and k in rk:
                return row[rk]
    return None


def fetch_tpex_quotes(data_date, prefer_openapi=True):
    """抓上櫃全部個股當日收盤（櫃買中心）。回傳與 fetch_quotes 相同結構的 list 或 None。
    先試 OpenAPI（僅最新交易日，需日期吻合），不合再用 dailyQuotes 指定日期回補。
    回補歷史時傳 prefer_openapi=False 直接走指定日期端點。"""
    y, m, d = data_date.split("-")
    roc_slash = f"{int(y) - 1911}/{m}/{d}"          # 115/07/13
    roc_compact = roc_slash.replace("/", "")         # 1150713

    def norm(code, name, close, change, vol):
        close = to_float(close)
        vol = to_float(vol)
        if not code or not str(code).strip().isdigit() or len(str(code).strip()) != 4:
            return None
        if close is None or vol is None:
            return None
        change = to_float(change)
        chg_pct = None
        if change is not None and (close - change):
            chg_pct = round(change / (close - change) * 100, 2)
        return {"code": str(code).strip(), "name": str(name or code).strip(),
                "close": close, "change_pct": chg_pct if chg_pct is not None else 0.0,
                "volume": vol, "market": "OTC"}

    # 1) OpenAPI：回傳整個 list，各列含 Date（民國 1150713）
    if prefer_openapi:
        data = fetch_json_retry(TPEX_DAILY, "上櫃收盤 OpenAPI", tries=2)
        if isinstance(data, list) and data:
            row_date = str(_pick(data[0], "Date") or "").replace("/", "")
            if not row_date or row_date == roc_compact:
                out = []
                for row in data:
                    q = norm(_pick(row, "SecuritiesCompanyCode", "Code"),
                             _pick(row, "CompanyName", "Name"),
                             _pick(row, "Close"), _pick(row, "Change"),
                             _pick(row, "TradingShares", "TradingVolume", "TradeVolume"))
                    if q:
                        out.append(q)
                if out:
                    return out
            else:
                print(f"  上櫃 OpenAPI 日期 {row_date} 與 {roc_compact} 不符，改用日期回補。")
        time.sleep(2)

    # 2) dailyQuotes 指定日期（結構為 tables[{fields,data}]，欄位名容錯）
    data = fetch_json_retry(TPEX_DAILY_BY_DATE.format(roc=roc_slash), f"上櫃收盤 {roc_slash}", tries=2)
    if not isinstance(data, dict):
        return None
    tables = data.get("tables") or []
    for t in tables:
        fields = t.get("fields", [])

        def idx(*names):
            for n in names:
                for i, f in enumerate(fields):
                    if n in f:
                        return i
            return None

        i_code = idx("代號")
        i_name = idx("名稱")
        i_close = idx("收盤")
        i_chg = idx("漲跌")
        i_vol = idx("成交股數", "成交量")
        if i_code is None or i_close is None or i_vol is None:
            continue
        out = []
        for row in t.get("data", []):
            try:
                q = norm(row[i_code], row[i_name] if i_name is not None else None,
                         row[i_close], row[i_chg] if i_chg is not None else None, row[i_vol])
            except Exception:
                continue
            if q:
                out.append(q)
        if out:
            return out
    return None


def fetch_index(data_date):
    """抓 data_date 當日的加權指數收盤與漲跌%（FMTQIK 市場成交資訊）。
    回傳 {"name","close","change","chg_pct"} 或 None。"""
    ymd = data_date.replace("-", "")
    data = fetch_json_retry(FMTQIK.format(date=ymd), "大盤指數 FMTQIK", tries=2)
    if not data or data.get("stat") != "OK":
        return None
    fields = data.get("fields", [])

    def idx(*names):
        for n in names:
            for i, f in enumerate(fields):
                if n in f:
                    return i
        return None

    i_date = idx("日期")
    i_close = idx("發行量加權股價指數", "加權股價指數", "加權指數")
    i_chg = idx("漲跌點數")
    if i_date is None or i_close is None:
        return None
    y, m, d = data_date.split("-")
    roc_date = f"{int(y) - 1911}/{m}/{d}"  # 證交所用民國年 115/07/13
    for row in data.get("data", []):
        if str(row[i_date]).strip() != roc_date:
            continue
        close = to_float(row[i_close])
        change = to_float(row[i_chg]) if i_chg is not None else None
        if close is None:
            return None
        chg_pct = None
        if change is not None and (close - change):
            chg_pct = round(change / (close - change) * 100, 2)
        return {"name": "加權指數", "close": close, "change": change, "chg_pct": chg_pct}
    print(f"  FMTQIK 找不到 {roc_date} 的資料列。")
    return None


def main():
    now = datetime.now(TZ)
    print(f"[{now.isoformat()}] 開始抓取台股資料 ...")

    try:
        industry_lookup = build_industry_lookup()
        print(f"  產業別對照：{len(industry_lookup)} 檔")
    except Exception as e:
        print(f"  ! 產業別抓取失敗：{e}", file=sys.stderr)
        sys.exit(1)

    time.sleep(2)  # 禮貌間隔，避開流量限制

    try:
        quotes = fetch_quotes()
    except Exception as e:
        print(f"  ! 個股成交抓取失敗：{e}", file=sys.stderr)
        sys.exit(1)

    if not quotes:
        # STOCK_DAY_ALL 失敗 → 改用 MI_INDEX 從「今天」往回找最近交易日
        # （back=0 涵蓋交易日當天 STOCK_DAY_ALL 被擋、但 MI_INDEX 正常的情況）
        print("  當日 STOCK_DAY_ALL 無資料，改用 MI_INDEX 從今天往回找 ...")
        used_date = None
        for back in range(0, 8):
            d = (now - timedelta(days=back)).strftime("%Y%m%d")
            time.sleep(2)  # 禮貌間隔
            q = fetch_quotes_by_date(d)
            if q:
                quotes = q
                used_date = d
                print(f"  已取得 {d} 的資料：{len(q)} 檔")
                break
        if not quotes:
            print("  近 7 日皆無資料，保留既有 data.json。")
            sys.exit(0)
        data_date = used_date[:4] + "-" + used_date[4:6] + "-" + used_date[6:]
    else:
        data_date = now.strftime("%Y-%m-%d")

    print(f"  有效個股（上市）：{len(quotes)} 檔")

    # 併入上櫃報價（失敗不影響上市資料）
    time.sleep(2)  # 禮貌間隔
    try:
        tpex = fetch_tpex_quotes(data_date)
    except Exception as e:
        print(f"  ! 上櫃報價抓取異常（略過）：{e}")
        tpex = None
    if tpex:
        seen = {q["code"] for q in quotes}
        added = [q for q in tpex if q["code"] not in seen]
        quotes = quotes + added
        print(f"  併入上櫃：{len(added)} 檔（合計 {len(quotes)}）")
    else:
        print("  上櫃報價無資料，僅用上市。")

    sectors = aggregate_by_sector(quotes, industry_lookup)
    print(f"  彙總板塊：{len(sectors)} 個")
    if not sectors:
        # 產業別 CSV 被限流回 HTML 時 lookup 會是空的 → 不可用空陣列覆蓋好資料
        try:
            with open("data.json", encoding="utf-8") as f:
                sectors = json.load(f).get("heatmap", [])
            print(f"  ! 彙總為空（產業別對照可能被限流），沿用上次 heatmap（{len(sectors)} 板塊）。")
        except Exception:
            print("  ! 彙總為空且無舊 data.json 可沿用。")

    themes, stock_chg = build_theme_payload(quotes, data_date)
    if themes is not None:
        print(f"  主題聚合：{len(themes)} 個主題、{len(stock_chg)} 檔個股漲跌")

    time.sleep(2)  # 禮貌間隔
    market_index = fetch_index(data_date)
    if market_index:
        print(f"  加權指數：{market_index['close']}（{market_index['chg_pct']}%）")
    else:
        print("  ! 加權指數抓取失敗，前端將維持上次/樣板值。")

    payload = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "data_date": data_date,
        "market": "TW",
        "source": "TWSE STOCK_DAY_ALL / MI_INDEX / FMTQIK + TPEx dailyQuotes + t187ap03_L/O",
        "note": "板塊漲跌為成交金額加權；面積為當日成交金額(億元)近似，非真實市值。含上市與上櫃。",
        "heatmap": sectors,
    }
    if themes is not None:
        payload["themes"] = themes       # 資金流向極細主題（真實量價）
        payload["stock_chg"] = stock_chg  # 個股漲跌 {code:{d,w}}，供關係圖配色
    if market_index:
        payload["index"] = market_index   # 大盤加權指數（標題列用）
    # 全市場「股名→當日漲跌」對照：供應鏈各主題視圖的公司標籤用
    # （涵蓋上市+上櫃全部個股，master 名單以外的公司也能顯示真實漲跌）
    payload["name_chg"] = {q["name"]: q["change_pct"] for q in quotes}

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  已寫入 data.json（{len(sectors)} 板塊）")


if __name__ == "__main__":
    main()
