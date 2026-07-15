#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
掃描 reports/daily 與 reports/weekly 下的 Markdown 與 HTML 報告，
產生 reports/index.json 供前端「報告」分頁列出。

檔名慣例：
- Markdown：YYYY-MM-DD.md（週報用該週最後一天或產出日）
- HTML：檔名含 YYYY-MM-DD 或 YYYYMMDD 皆可（例 digitimes_daily_20260715.html）
標題：Markdown 取第一個「# 」開頭的行；HTML 取 <title> 或第一個 <h1>；
都沒有就用日期當標題。

GitHub Actions 會在 reports/ 有新 push 時自動執行本腳本；
本機排程只要把 .md 放進資料夾推上去即可，不必手動維護 index.json。
"""

import json
import os
import re

REPORTS_DIR = "reports"
KINDS = ["daily", "weekly"]

DATE_RE = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")


def md_title(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
    return None


def html_title(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        head = f.read(65536)
    for pat in (r"<title[^>]*>(.*?)</title>", r"<h1[^>]*>(.*?)</h1>"):
        m = re.search(pat, head, re.IGNORECASE | re.DOTALL)
        if m:
            t = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if t:
                return t
    return None


def scan(kind):
    folder = os.path.join(REPORTS_DIR, kind)
    if not os.path.isdir(folder):
        return []
    out = []
    for fn in os.listdir(folder):
        is_md = fn.endswith(".md")
        is_html = fn.endswith(".html") or fn.endswith(".htm")
        if not (is_md or is_html):
            continue
        m = DATE_RE.search(fn)
        if not m:
            continue
        date = "-".join(m.groups())
        title = None
        try:
            title = md_title(os.path.join(folder, fn)) if is_md \
                else html_title(os.path.join(folder, fn))
        except Exception:
            pass
        out.append({"date": date, "file": f"{kind}/{fn}", "title": title or date})
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
