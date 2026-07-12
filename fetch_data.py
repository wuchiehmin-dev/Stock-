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
    """回傳 {股票代號: 產業別} 對照。"""
    rows = fetch_csv(COMPANY_LIST)
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
            lookup[code] = ind
    return lookup


def fetch_quotes():
    """回傳 list[dict]，每檔含 code/name/close/change_pct/volume。
    非交易日（假日）證交所可能回空白或非 JSON，此時回傳 None 視為無資料。"""
    req = urllib.request.Request(STOCK_DAY_ALL, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8").strip()
    except Exception as e:
        print(f"  個股成交連線失敗（可能為非交易日）：{e}")
        return None
    if not raw:
        print("  個股成交回傳空白（非交易日或尚未收盤）。")
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        print("  個股成交回傳非 JSON（非交易日或來源維護中）。")
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
        print("  今日無成交資料（可能為非交易日），保留既有 data.json。")
        sys.exit(0)

    print(f"  有效個股：{len(quotes)} 檔")
    sectors = aggregate_by_sector(quotes, industry_lookup)
    print(f"  彙總板塊：{len(sectors)} 個")

    payload = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "market": "TW",
        "source": "TWSE STOCK_DAY_ALL + t187ap03_L",
        "note": "板塊漲跌為成交金額加權；面積為當日成交金額(億元)近似，非真實市值。",
        "heatmap": sectors,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  已寫入 data.json（{len(sectors)} 板塊）")


if __name__ == "__main__":
    main()
