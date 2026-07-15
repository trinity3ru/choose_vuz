# -*- coding: utf-8 -*-
"""
Прототип парсера УрФУ (urfu.ru) — ранжированные списки поступающих 2026.

Источник данных (обнаружен в разделе /ru/alpha/ranzhirovannye-spiski-postupajushchikh/):
    https://urfu.ru/api/entrants/files/rating-{УРОВЕНЬ}-{ИНСТИТУТ}-{ТИП}-{ОСНОВА}.html
      УРОВЕНЬ 0002 = бакалавриат/специалитет
      ИНСТИТУТ  001..017
      ТИП       01 = основной конкурс (в файле есть подсписки: основные места, особая/целевая квота)
      ОСНОВА    1 = бюджет, 2 = контракт

Каждый файл — один институт целиком (~7 МБ, десятки направлений).
Внутри чередуются пары таблиц: [META 2 колонки] + [DATA 10 колонок].
META.«Вид конкурса» == «Основные места в рамках КЦП» — это основной бюджетный конкурс.

Этот прототип: качает бюджетные файлы (-01-1) всех институтов, вытаскивает
целевые направления УрФУ (из «Список специальностей.docx») и пишет CSV + XLSX.
Скачанные HTML кешируются, повторный запуск быстрый.
"""
import csv
import re
import sys
import html
import time
from pathlib import Path

import requests

try:
    from openpyxl import Workbook
    HAVE_XLSX = True
except ImportError:
    HAVE_XLSX = False

BASE = "https://urfu.ru/api/entrants/files/rating-0002-{inst:03d}-01-1.html"
INSTITUTES = range(1, 18)  # 001..017
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Только основной бюджетный конкурс
COMPETITION_KIND = "Основные места в рамках КЦП"

# 20 уникальных целевых кодов УрФУ из «Список специальностей.docx»
TARGET_CODES = {
    "11.03.02", "10.05.02", "15.03.01", "27.03.04", "01.03.01",
    "09.03.03", "13.03.03", "02.03.01", "01.03.04", "09.03.04",
    "15.03.04", "27.05.01", "15.03.05", "13.03.02", "10.03.01",
    "15.03.06", "09.03.01", "02.03.03", "23.03.02", "27.03.03",
}

CACHE = Path(__file__).resolve().parent / "_urfu_cache"
OUT_DIR = Path(__file__).resolve().parents[2]  # корень проекта

TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
TABLE_RE = re.compile(r"<table.*?</table>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
CODE_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{2})\b")

DATA_HEADER = "Код поступающего (УКП)"


def clean(s: str) -> str:
    return WS_RE.sub(" ", html.unescape(TAG_RE.sub(" ", s))).strip()


def cells(tr: str):
    return [clean(c) for c in CELL_RE.findall(tr)]


def fetch(inst: int) -> str | None:
    CACHE.mkdir(exist_ok=True)
    fp = CACHE / f"inst-{inst:03d}.html"
    if fp.exists() and fp.stat().st_size > 1000:
        return fp.read_text(encoding="utf-8", errors="replace")
    url = BASE.format(inst=inst)
    try:
        r = requests.get(url, headers=UA, timeout=120)
    except requests.RequestException as e:
        print(f"  [{inst:03d}] сетевая ошибка: {e}")
        return None
    if r.status_code != 200 or len(r.content) < 1000:
        print(f"  [{inst:03d}] нет файла (HTTP {r.status_code}, {len(r.content)} б)")
        return None
    r.encoding = "utf-8"
    fp.write_text(r.text, encoding="utf-8")
    print(f"  [{inst:03d}] скачано {len(r.content) // 1024} КБ")
    return r.text


def parse_meta(tab: str) -> dict:
    """META-таблица: пары ключ :: значение."""
    meta = {}
    for tr in TR_RE.findall(tab):
        c = cells(tr)
        if len(c) == 2 and c[0]:
            meta[c[0]] = c[1]
    return meta


def parse_file(inst: int, htmltext: str):
    """Возвращает список dict-строк абитуриентов по целевым направлениям."""
    rows = []
    tables = TABLE_RE.findall(htmltext)
    current_meta = None
    for tab in tables:
        trs = TR_RE.findall(tab)
        if not trs:
            continue
        header = cells(trs[0])
        # DATA-таблица?
        if header and DATA_HEADER in " ".join(header):
            if not current_meta:
                continue
            napr = current_meta.get("Направление (образовательная программа)", "")
            m = CODE_RE.search(napr)
            code = m.group(1) if m else ""
            kind = current_meta.get("Вид конкурса", "")
            if code not in TARGET_CODES or kind != COMPETITION_KIND:
                continue
            for tr in trs[1:]:
                c = cells(tr)
                if len(c) < 10 or not c[0].isdigit():
                    continue
                rows.append({
                    "институт": current_meta.get("Институт (филиал)", ""),
                    "код": code,
                    "направление": napr,
                    "вид_конкурса": kind,
                    "уровень": current_meta.get("Уровень ВО", ""),
                    "место": c[0],
                    "укп": c[1],
                    "согласие": c[2],
                    "приоритет": c[3],
                    "ви_предметы": c[4],
                    "бви": c[5],
                    "общие_ид": c[6],
                    "целевые_ид": c[7],
                    "сумма_баллов": c[8],
                    "преим_право": c[9],
                })
        else:
            meta = parse_meta(tab)
            if "Направление (образовательная программа)" in meta:
                current_meta = meta
    return rows


def main():
    print("Парсинг УрФУ — бюджет, основной конкурс (Основные места в рамках КЦП)")
    all_rows = []
    for inst in INSTITUTES:
        htmltext = fetch(inst)
        if not htmltext:
            continue
        r = parse_file(inst, htmltext)
        if r:
            found = sorted(set(x["код"] for x in r))
            print(f"  [{inst:03d}] строк: {len(r):5d}  коды: {', '.join(found)}")
        all_rows.append(r) if False else all_rows.extend(r)
        time.sleep(0.3)

    print(f"\nВсего строк по целевым направлениям: {len(all_rows)}")
    got = sorted(set(x["код"] for x in all_rows))
    missing = sorted(TARGET_CODES - set(got))
    print(f"Найдено кодов: {len(got)}/{len(TARGET_CODES)}: {', '.join(got)}")
    if missing:
        print(f"НЕ найдено (нет бюджета / другой институт / нет набора): {', '.join(missing)}")

    if not all_rows:
        print("Пусто — проверь источник.")
        return

    fields = list(all_rows[0].keys())
    csv_path = OUT_DIR / "urfu_budget_lists.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)
    print(f"CSV:  {csv_path}")

    if HAVE_XLSX:
        wb = Workbook()
        ws = wb.active
        ws.title = "УрФУ бюджет"
        ws.append(fields)
        for row in all_rows:
            ws.append([row[k] for k in fields])
        xlsx_path = OUT_DIR / "urfu_budget_lists.xlsx"
        wb.save(xlsx_path)
        print(f"XLSX: {xlsx_path}")


if __name__ == "__main__":
    sys.exit(main())
