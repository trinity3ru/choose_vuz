"""Тест разбора xlsx СПбАУ без Playwright."""
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.parser.spbau_mapping import find_latest_xlsx_url, parse_xlsx

page_url = "https://www.spbau.ru/campaign/bachelor/documents"
html = urllib.request.urlopen(page_url).read().decode("utf-8")
xlsx_url = find_latest_xlsx_url(html, page_url)
print("xlsx:", xlsx_url)

content = urllib.request.urlopen(xlsx_url).read()
places, applicants, _ = parse_xlsx(content, "Очная", "Бюджетная основа")
print("places:", places)
print("applicants:", len(applicants))
print("agreements:", sum(1 for a in applicants if a.has_agreement))
print("bvi:", sum(1 for a in applicants if a.is_bvi))
if applicants:
    a = applicants[0]
    print("first:", a.applicant_code, a.total_score, a.exam_score, a.priority, a.has_agreement)
