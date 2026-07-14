# -*- coding: utf-8 -*-
"""
Генератор направлений ВШЭ для config.json из каталога API pk.hse.ru.

Берёт ВСЕ программы бакалавриата кампусов Москва (HSE_MSK) и Санкт-Петербург
(HSE_SPB) и заводит по направлению на каждый список: бюджетный (placeType Б)
и платный (placeType К, код с суффиксом -К, имя с пометкой «(платное)»).

Коды направлений ВШЭ не уникальны (под 38.03.01 в Москве 7 программ),
поэтому программы одного кода получают суффиксы: 38.03.01, 38.03.01-2, ...
Суффикс присваивается детерминированно (по алфавиту названий программ).

Запуск повторяемый (идемпотентный): существующие в config.json направления
узнаются по external_id и сохраняют свои коды — история в БД не ломается;
добавляются только новые программы, на свободные суффиксы.

Запуск из каталога backend:
    python -X utf8 scripts/generate_hse_config.py            # применить
    python -X utf8 scripts/generate_hse_config.py --dry-run  # только показать
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BACKEND_DIR / "config.json"

CATALOG_URL = "https://pk.hse.ru/admissions/api/competitve-group"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# Кампус (filial каталога) -> код вуза в config.json.
CAMPUSES = {
    "Москва": "HSE_MSK",
    "Санкт-Петербург": "HSE_SPB",
}

PARAMS_BUDGET = {"study_form": "Очная", "finance_type": "Бюджетная основа"}
PARAMS_PAID = {"study_form": "Очная", "finance_type": "Контракт"}


def fetch_catalog() -> dict:
    resp = httpx.get(CATALOG_URL, timeout=60, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def collect_programs(catalog: dict, filial_name: str) -> list[dict]:
    """Программы бакалавриата кампуса: код направления, имя, группы Б/К."""
    filial = next(f for f in catalog["filials"] if f["name"] == filial_name)
    programs: list[dict] = []
    for direction in filial["trainingDirections"]:
        code = direction["name"]["code"]
        for program in direction["educationPrograms"]:
            level = (program.get("educationLevel") or {}).get("code", "")
            if not level.strip().startswith("б"):  # только бакалавриат
                continue
            groups = {}
            for group in program["competitiveGroups"]:
                ptype = group["placeType"]["code"]
                if ptype in ("Б", "К"):
                    groups[ptype] = (
                        f"{group['setOfCompetitiveGroup']['id']}/{group['id']}"
                    )
            if groups:
                programs.append(
                    {"code": code, "name": program["name"], "groups": groups}
                )
    return programs


def assign_codes(programs: list[dict], taken_by_ext: dict[str, str]) -> list[dict]:
    """
    Присвоить программам уникальные коды направлений.

    taken_by_ext: external_id (бюджетный ИЛИ платный) -> уже занятый базовый код
    из текущего config.json — такие программы сохраняют свой код.
    """
    result: list[dict] = []
    used_codes: set[str] = set(taken_by_ext.values())

    # Детерминированный порядок: по коду, затем по названию программы.
    for program in sorted(programs, key=lambda p: (p["code"], p["name"])):
        existing = None
        for ext in program["groups"].values():
            if ext in taken_by_ext:
                existing = taken_by_ext[ext]
                break

        if existing is not None:
            base = existing
        else:
            base = program["code"]
            suffix = 2
            while base in used_codes:
                base = f"{program['code']}-{suffix}"
                suffix += 1

        used_codes.add(base)
        result.append({**program, "base_code": base})
    return result


def build_majors(programs: list[dict]) -> list[dict]:
    """Собрать записи majors (бюджет + платное) из программ с кодами."""
    majors: list[dict] = []
    for program in programs:
        if "Б" in program["groups"]:
            majors.append(
                {
                    "code": program["base_code"],
                    "name": program["name"],
                    "params": PARAMS_BUDGET,
                    "external_id": program["groups"]["Б"],
                }
            )
        if "К" in program["groups"]:
            majors.append(
                {
                    "code": f"{program['base_code']}-К",
                    "name": f"{program['name']} (платное)",
                    "params": PARAMS_PAID,
                    "external_id": program["groups"]["К"],
                }
            )
    return majors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="только показать изменения")
    args = parser.parse_args()

    catalog = fetch_catalog()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    by_code = {u["code"]: u for u in config["universities"]}

    for filial_name, uni_code in CAMPUSES.items():
        uni = by_code.get(uni_code)
        if uni is None:
            print(f"ВНИМАНИЕ: вуза {uni_code} нет в config.json — пропуск")
            continue

        # Существующие направления: external_id -> базовый код (без -К).
        taken_by_ext: dict[str, str] = {}
        existing_exts = set()
        for major in uni["majors"]:
            ext = major.get("external_id") or ""
            existing_exts.add(ext)
            base = major["code"][:-2] if major["code"].endswith("-К") else major["code"]
            taken_by_ext[ext] = base

        programs = collect_programs(catalog, filial_name)
        majors = build_majors(assign_codes(programs, taken_by_ext))

        new_majors = [m for m in majors if m["external_id"] not in existing_exts]
        by_finance = defaultdict(int)
        for m in new_majors:
            by_finance[m["params"]["finance_type"]] += 1

        print(
            f"{uni_code} ({filial_name}): программ {len(programs)}, "
            f"направлений всего {len(majors)}, уже в конфиге "
            f"{len(majors) - len(new_majors)}, добавляется {len(new_majors)} "
            f"(бюджет {by_finance['Бюджетная основа']}, платное {by_finance['Контракт']})"
        )
        for m in new_majors[:6]:
            print(f"   + {m['code']:16} {m['name'][:55]}")
        if len(new_majors) > 6:
            print(f"   ... и ещё {len(new_majors) - 6}")

        if not args.dry_run:
            uni["majors"].extend(new_majors)

    if args.dry_run:
        print("\n--dry-run: config.json не изменён")
        return 0

    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nconfig.json обновлён: {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
