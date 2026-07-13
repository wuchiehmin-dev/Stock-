#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回補 history_tw.json 過去交易日的主題資料（上市 + 上櫃）。可重複執行、自動續跑。

用途：讓「板塊資金流向」的週(5日)/月(21日)動能立即有完整歷史可算。

證交所對雲端 IP 限流很兇（連續查 MI_INDEX 幾次就回 307），因此：
  - 請求間隔拉長（PAUSE 秒）
  - 偵測到疑似限流（連線/HTTP 錯誤、非 JSON）時，冷卻 60/180 秒再重試
  - 冷卻後仍被擋就先收工，把已補到的天數 commit 起來；再跑一次會從缺的日期接續
  - 已完整（含上櫃報價）的日期自動跳過，不重抓

跑完請接著跑 fetch_data.py 重算 data.json 的週/月數值（workflow 已串好）。
"""

import json
import sys
import time
from datetime import datetime, timedelta

import fetch_data as fd

TARGET_DAYS = 22      # 今天 + 21 個歷史交易日，足夠算月動能
MAX_LOOKBACK = 45     # 最多往回掃 45 個日曆日（涵蓋連假）
PAUSE = 6             # 每個日期之間的基本間隔（秒）
COOLDOWNS = [60, 180]  # 疑似限流時的冷卻梯度（秒）
COMPLETE_STOCKS = 100  # 該日成分股報價達此數視為完整（含上櫃），跳過不重抓


def fetch_day(ymd):
    """抓單日上市報價，區分「休市」與「被限流」。
    回傳 (quotes, blocked)：quotes=None 且 blocked=True 表示冷卻後仍被擋。"""
    for i, cooldown in enumerate([0] + COOLDOWNS):
        if cooldown:
            print(f"  疑似被限流，冷卻 {cooldown}s 後重試（第{i}次）...")
            time.sleep(cooldown)
        quotes = fd.fetch_quotes_by_date(ymd)
        if quotes:
            return quotes, False
        if fd.LAST_ERROR is None:
            return None, False  # 來源正常回應但無資料 → 休市
    return None, True


def main():
    now = datetime.now(fd.TZ)
    history = fd.load_history()
    got = 0
    blocked_stop = False

    for back in range(0, MAX_LOOKBACK + 1):
        if got >= TARGET_DAYS:
            break
        day = now - timedelta(days=back)
        if day.weekday() >= 5:  # 週末直接跳過，省請求
            continue
        ymd = day.strftime("%Y%m%d")
        date_key = day.strftime("%Y-%m-%d")

        prev = history.get(date_key)
        if prev and len(prev.get("stocks", {})) >= COMPLETE_STOCKS:
            got += 1
            print(f"[{date_key}] 已完整（{len(prev['stocks'])} 檔），跳過。")
            continue

        print(f"[{date_key}] 抓取中 ...")
        time.sleep(PAUSE)
        quotes, blocked = fetch_day(ymd)
        if blocked:
            print("  冷卻後仍被限流，先收工保留已補天數；稍後再跑一次即可接續。")
            blocked_stop = True
            break
        if not quotes:
            print("  休市，跳過。")
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

    if blocked_stop and len(dates) < TARGET_DAYS:
        print(f"※ 尚缺 {TARGET_DAYS - len(dates)} 個交易日，過幾分鐘後再 Run 一次本 workflow 接續回補。")
    if not dates:
        print("! 一天都沒有，請檢查資料源。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
