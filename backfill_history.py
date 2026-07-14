#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回補過去交易日的「每日快照」（prices/YYYY-MM-DD.json，上市 + 上櫃全市場）。
可重複執行、自動續跑；跑完由 fetch_data.py 從快照重建 data.json 與週/月動能。

證交所對雲端 IP 限流很兇（連續查 MI_INDEX 幾次就回 307），因此：
  - 請求間隔拉長（PAUSE 秒）
  - 偵測到疑似限流（連線/HTTP 錯誤、非 JSON）時，冷卻 60/180 秒再重試
  - 冷卻後仍被擋就先收工，把已補到的快照 commit 起來；再跑一次會從缺的日期接續
  - 已完整（含上櫃、達門檻檔數）的快照自動跳過，不重抓
"""

import sys
import time
from datetime import datetime, timedelta

import fetch_data as fd

TARGET_DAYS = 22       # 今天 + 21 個歷史交易日，足夠算月動能
MAX_LOOKBACK = 45      # 最多往回掃 45 個日曆日（涵蓋連假）
PAUSE = 6              # 每個請求之間的基本間隔（秒）
COOLDOWNS = [60, 180]  # 疑似限流時的冷卻梯度（秒）
COMPLETE_STOCKS = 1500  # 快照達此檔數視為完整（上市+上櫃全市場約 1900 檔）


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
    got = 0
    blocked_stop = False

    for back in range(0, MAX_LOOKBACK + 1):
        if got >= TARGET_DAYS:
            break
        day = now - timedelta(days=back)
        if day.weekday() >= 5:  # 週末直接跳過，省請求
            continue
        if back == 0 and now.hour < 14:
            continue  # 盤中不抓今天（半套資料），與 fetch_data 的防呆一致
        ymd = day.strftime("%Y%m%d")
        date_key = day.strftime("%Y-%m-%d")

        snap = fd.load_snapshot(date_key)
        if snap and len(snap.get("stocks", {})) >= COMPLETE_STOCKS:
            got += 1
            print(f"[{date_key}] 快照已完整（{len(snap['stocks'])} 檔），跳過。")
            continue

        print(f"[{date_key}] 抓取中 ...")
        time.sleep(PAUSE)
        quotes, blocked = fetch_day(ymd)
        if blocked:
            print("  冷卻後仍被限流，先收工保留已補快照；稍後再跑一次即可接續。")
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

        snap = fd.save_snapshot(date_key, quotes)  # 指數留給主流程補當日即可
        got += 1
        print(f"  快照完成：{len(snap['stocks'])} 檔（累計 {got}/{TARGET_DAYS} 交易日）")

    dates = fd.snapshot_dates()
    print(f"快照共 {len(dates)} 個交易日" + (f"（{dates[0]} ~ {dates[-1]}）" if dates else ""))

    if blocked_stop and len(dates) < TARGET_DAYS:
        print(f"※ 尚缺約 {TARGET_DAYS - len(dates)} 個交易日，過幾分鐘後再 Run 一次接續回補。")
    if not dates:
        print("! 一個快照都沒有，請檢查資料源。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
