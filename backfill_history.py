#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性回補 history_tw.json 過去交易日的主題資料（上市 + 上櫃）。

用途：讓「板塊資金流向」的週(5日)/月(21日)動能立即有完整歷史可算，
不必等排程慢慢累積。跑一次即可，之後由每日排程接續。

資料源：
  - 上市：TWSE MI_INDEX（可指定日期）
  - 上櫃：TPEx dailyQuotes（可指定日期）

會覆蓋範圍內既有的日期（確保舊紀錄也含上櫃股），跑完請接著跑
fetch_data.py 重算 data.json 的週/月數值。
"""

import json
import sys
import time
from datetime import datetime, timedelta

import fetch_data as fd

TARGET_DAYS = 22   # 今天 + 21 個歷史交易日，足夠算月動能
MAX_LOOKBACK = 45  # 最多往回掃 45 個日曆日（涵蓋連假）
PAUSE = 3          # 每個請求間隔秒數（證交所限每 5 秒 3 個 request）


def main():
    now = datetime.now(fd.TZ)
    history = fd.load_history()
    got = 0

    for back in range(0, MAX_LOOKBACK + 1):
        if got >= TARGET_DAYS:
            break
        day = now - timedelta(days=back)
        if day.weekday() >= 5:  # 週末直接跳過，省請求
            continue
        ymd = day.strftime("%Y%m%d")
        date_key = day.strftime("%Y-%m-%d")
        print(f"[{date_key}] 抓取中 ...")

        time.sleep(PAUSE)
        quotes = fd.fetch_quotes_by_date(ymd)
        if not quotes:
            print("  無上市資料（休市或來源無此日），跳過。")
            continue

        time.sleep(PAUSE)
        try:
            tpex = fd.fetch_tpex_quotes(date_key, prefer_openapi=False)
        except Exception as e:
            print(f"  上櫃抓取異常（僅用上市）：{e}")
            tpex = None
        if tpex:
            seen = {q["code"] for q in quotes}
            quotes = quotes + [q for q in tpex if q["code"] not in seen]

        day_themes, day_stocks, _ = fd.compute_day_record(quotes)
        if day_themes is None:
            print("  ! 主檔缺失，中止。", file=sys.stderr)
            sys.exit(1)
        history[date_key] = {"themes": day_themes, "stocks": day_stocks}
        got += 1
        print(f"  完成：{len(day_stocks)} 檔成分股有報價（累計 {got}/{TARGET_DAYS} 交易日）")

    dates = sorted(history.keys(), reverse=True)[:fd.HISTORY_KEEP_DAYS]
    history = {d: history[d] for d in dates}
    with open(fd.HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False)
    print(f"history_tw.json 共 {len(dates)} 個交易日（{dates[-1]} ~ {dates[0]}）")

    if got == 0:
        print("! 一天都沒抓到，請檢查資料源。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
