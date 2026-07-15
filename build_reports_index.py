#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
掃描 reports/daily 與 reports/weekly 下的 Markdown 報告，
產生 reports/index.json 供前端「報告」分頁列出。

檔名慣例：YYYY-MM-DD.md（週報用該週最後一天或產出日）。
標題取檔案第一個「# 」開頭的行；沒有就用日期當標題。

GitHub Actions 會在 reports/ 有新 push 時自動執行本腳本；
本機排程只要把 .md 放進資料夾推上去即可，不必手動維護 index.json。
"""

import json
import os
import re

REPORTS_DIR = "reports"
KINDS = ["daily", "weekly"]


def scan(kind):
    folder = os.path.join(REPORTS_DIR, kind)
    if not os.path.isdir(folder):
        return []
    out = []
    for fn in os.listdir(folder):
        m = re.match(r"^(\d{4}-\d{2}-\d{2}).*\.md$", fn)
        if not m:
            continue
        title = None
        try:
            with open(os.path.join(folder, fn), encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
        except Exception:
            pass
        out.append({"date": m.group(1), "file": f"{kind}/{fn}", "title": title or m.group(1)})
    out.sort(key=lambda x: (x["date"], x["file"]), reverse=True)
    return out


def main():
    index = {kind: scan(kind) for kind in KINDS}
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, "index.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    print(f"reports/index.json：每日 {len(index['daily'])} 篇、週報 {len(index['weekly'])} 篇")


if __name__ == "__main__":
    main()
