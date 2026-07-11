"""Разведка страницы документов СПбАУ (Алферовский университет)."""
import re
import urllib.request

url = "https://www.spbau.ru/campaign/bachelor/documents"
html = urllib.request.urlopen(url).read().decode("utf-8")

# Все ссылки
links = re.findall(r'href=["\']([^"\']+)["\']', html)
for link in links:
    if any(x in link.lower() for x in ("xlsx", "xls", "download", "file", "upload")):
        print("LINK:", link)

# Таблица со списками
for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE):
    row = m.group(1)
    if "xlsx" in row.lower() or "основной" in row.lower():
        print("ROW:", re.sub(r"\s+", " ", row)[:500])
