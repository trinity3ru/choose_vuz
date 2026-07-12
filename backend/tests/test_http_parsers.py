"""
Тесты HTTP-парсеров (11 вузов, httpx без браузера).

Каждый парсер гоняется целиком через parse() на фикстуре, повторяющей
реальную разметку сайта (см. mapping-модули). Проверяются: статус запуска,
число строк, места, согласия и точечные поля абитуриента.
"""

import io
import json

import httpx
import openpyxl
import pytest

from app.parser.guap import GuapParser
from app.parser.hse import HseParser
from app.parser.itmo import ItmoParser
from app.parser.kpfu import KpfuParser
from app.parser.leti import LetiParser
from app.parser.mpei import MpeiParser
from app.parser.samara import SamaraParser
from app.parser.samgtu import SamgtuParser
from app.parser.spbau import SpbauParser
from app.parser.spbgu import SpbguParser
from app.parser.spmi import SpmiParser
from app.parser.tltsu import TltsuParser

from .conftest import make_major, make_university, mock_client


# ----------------------------------------------------------------- ИТМО --


def _itmo_html() -> str:
    next_data = {
        "props": {
            "pageProps": {
                "programList": {
                    "general_competition": [
                        {
                            "sspvo_id": 4900001,
                            "total_scores": 280,
                            "exam_scores": 270,
                            "ia_scores": 10,
                            "priority": 1,
                            "is_send_agreement": True,
                            "status": None,
                        },
                        {
                            "sspvo_id": 4900002,
                            "total_scores": 0,
                            "exam_scores": 0,
                            "ia_scores": 0,
                            "priority": 3,
                            "is_send_agreement": False,
                            "status": "pass_another",
                        },
                    ],
                    "direction": {
                        "competitive_group_id": 2342,
                        "budget_min": 50,
                        "target_reception": 5,
                        "special_quota": 5,
                        "invalid": 5,
                    },
                    "update_time": "2026-07-10 21:00",
                }
            }
        }
    }
    return (
        "<html><body><div id='app'></div>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>'
        "</body></html>"
    )


async def test_itmo_parser():
    uni = make_university(
        "ITMO",
        "https://abit.itmo.ru/rating/bachelor/budget",
        [make_major("09.03.04", external_id="2342")],
    )
    parser = ItmoParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/2342")
        return httpx.Response(200, text=_itmo_html())

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "success"
    assert len(result.majors) == 1
    major = result.majors[0]
    assert major.summary.places == 35  # 50 - 5 - 5 - 5
    assert major.summary.applications == 2
    assert major.summary.agreements == 1
    assert major.internal_id == 2342
    first = major.applicants[0]
    assert first.applicant_code == "4900001"
    assert first.total_score == 280
    assert first.has_agreement is True
    # Ноль баллов у ИТМО = «не введены» -> None.
    assert major.applicants[1].total_score is None


# --------------------------------------------------------------- Самара --


def _samara_html() -> str:
    row1 = (
        "<tr><td>1</td><td>1234567</td><td>250</td><td>80</td><td>90</td><td>80</td>"
        "<td>10</td><td>Да</td><td>1</td><td>Подано</td><td>Да</td><td>-</td></tr>"
    )
    row2 = (
        "<tr><td>2</td><td>7654321</td><td>240</td><td>78</td><td>85</td><td>77</td>"
        "<td>5</td><td>Нет</td><td>2</td><td>Подано</td><td>Нет</td><td>-</td></tr>"
    )
    return (
        "<html><body>"
        '<div class="text"> Общий конкурс </div><div class="numb"> 208 / 29 </div>'
        '<table id="bak_table_id2"><tr><th colspan="12">Общий конкурс</th></tr>'
        f"{row1}{row2}</table></body></html>"
    )


async def test_samara_parser():
    uni = make_university(
        "SAMARA",
        "https://priemsamara.ru/ratings/",
        [make_major("01.03.02", external_id="2")],
    )
    parser = SamaraParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["pk"] == "2"
        assert request.url.params["pay"] == "budget"
        return httpx.Response(200, text=_samara_html())

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "success"
    major = result.majors[0]
    assert major.summary.places == 29
    assert major.summary.applications == 2
    assert major.summary.agreements == 1
    first = major.applicants[0]
    assert first.applicant_code == "1234567"
    assert first.total_score == 250
    assert first.achievement_score == 10
    assert first.priority == 1
    assert first.has_agreement is True


# --------------------------------------------------------------- СамГТУ --


async def test_samgtu_parser():
    kcps = [
        {
            "items": [
                {
                    "CompetetiveGroupID": "777",
                    "CompetetiveGroupName": "09.03.04 Программная инженерия",
                    "StudyFormName": "Очная",
                    "Representation": "СамГТУ",
                    "PlaceTypeID": 1,
                    "KCP": "25",
                }
            ]
        }
    ]
    rating = [
        {
            "siteName": "111222",
            "IsNoExam": "0",
            "SummaAll": "282.00",
            "EGE_sum": "272",
            "IndividualAchivment": "10",
            "Benefit": "0",
            "OriginalReceived": "1",
            "PriorityNumber": "1",
            "PlaceTypeID": 1,
        },
        # Строка другой категории (особая квота) — должна быть отфильтрована.
        {
            "siteName": "999888",
            "IsNoExam": "0",
            "SummaAll": "200.00",
            "PlaceTypeID": 2,
        },
    ]

    uni = make_university(
        "SAMGTU",
        "https://samgtu.ru/admission/competetivegroup",
        [make_major("09.03.04")],
    )
    parser = SamgtuParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Referer"] == "https://samgtu.ru/admission/competetivegroup"
        if request.url.path.endswith("/kcps"):
            return httpx.Response(200, json=kcps)
        if request.url.path.endswith("/rating"):
            assert request.url.params["id"] == "777"
            return httpx.Response(200, json=rating)
        return httpx.Response(404)

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "success"
    major = result.majors[0]
    assert major.summary.places == 25
    assert major.summary.applications == 1  # квота отфильтрована
    assert major.summary.agreements == 1
    first = major.applicants[0]
    assert first.applicant_code == "111222"
    assert first.total_score == 282
    assert first.exam_score == 272
    assert first.achievement_score == 10


# ---------------------------------------------------------------- СПбГУ --


def _spbgu_block_html() -> str:
    header = (
        "<table><tr><th>Количество бюджетных мест:</th><td>20</td></tr></table>"
    )
    row = (
        "<tr>"
        "<td>1</td><td>5551112</td><td>290</td><td>280</td>"
        "<td>95</td><td>95</td><td>90</td><td>10</td>"
        "<td>Нет</td><td>Нет</td><td>Да</td><td>1</td><td>Подано</td>"
        "</tr>"
    )
    return f"{header}<table>{row}</table>"


async def test_spbgu_parser():
    meta = {
        "id": "report-1",
        "report_upload_id": "upload-1",
        "sections": [
            {"specialities": [{"id": "sp-uuid-1", "code": "03.03.02", "name": "Физика"}]}
        ],
    }
    page_html = (
        "<html><head></head><body>"
        f'<script type="application/json" id="priem-list-02-report-meta">{json.dumps(meta)}</script>'
        "</body></html>"
    )

    uni = make_university(
        "SPBGU",
        "https://enrollelists.spbu.ru/reports/PriemList02.php",
        [make_major("03.03.02")],
    )
    parser = SpbguParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=page_html)
        # POST /api/reports/priem-list-02/data
        payload = json.loads(request.content)
        assert payload["report_priem_list_02_id"] == "report-1"
        assert payload["speciality_ids"] == ["sp-uuid-1"]
        return httpx.Response(200, json={"blocks": [{"html": _spbgu_block_html()}]})

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "success"
    major = result.majors[0]
    assert major.summary.places == 20
    assert major.summary.applications == 1
    assert major.summary.agreements == 1
    first = major.applicants[0]
    assert first.applicant_code == "5551112"
    assert first.total_score == 290
    assert first.exam_score == 280
    assert first.achievement_score == 10
    assert first.priority == 1


# ------------------------------------------------------------------ ТГУ --


def _tltsu_html() -> str:
    row = (
        "<tr>"
        "<td>1</td><td>2223334</td><td>1</td><td>Подано</td><td></td>"
        "<td>Электронное</td><td></td><td>ЕГЭ</td>"
        "<td>230</td><td>7</td><td>237</td>"
        "</tr>"
    )
    return (
        "<html><body>"
        '<div class="style_7">01.03.02 Прикладная математика и информатика</div>'
        '<div class="style_7">Основные места в рамках КЦП (бюджет) - 16 мест.</div>'
        f"<table>{row}</table>"
        "</body></html>"
    )


async def test_tltsu_parser():
    uni = make_university(
        "TLTSU",
        "http://edu.tltsu.ru:8888/birt-viewer/preview?__report=x&__format=html",
        [make_major("01.03.02"), make_major("09.03.04")],
    )
    parser = TltsuParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_tltsu_html())

    mock_client(parser, handler)
    result = await parser.parse()

    # 01.03.02 найден, 09.03.04 в отчёте нет -> partial.
    assert result.status == "partial"
    assert len(result.majors) == 1
    major = result.majors[0]
    assert major.code == "01.03.02"
    assert major.summary.places == 16
    assert major.summary.agreements == 1
    first = major.applicants[0]
    assert first.applicant_code == "2223334"
    assert first.total_score == 237
    assert first.exam_score == 230
    assert first.achievement_score == 7
    assert first.has_agreement is True


# ----------------------------------------------------------------- ЛЭТИ --


def _leti_html() -> str:
    row_main = (
        "<tr><td>1</td><td>3334445</td><td>1</td><td>Основные места</td>"
        "<td>265</td><td>255</td><td>90</td><td>85</td><td>80</td>"
        "<td>10</td><td>-</td><td>Нет</td><td>Электронное</td><td>Участвует</td></tr>"
    )
    row_quota = (
        "<tr><td>2</td><td>9998887</td><td>1</td><td>Особая квота</td>"
        "<td>200</td><td>195</td><td>70</td><td>65</td><td>60</td>"
        "<td>5</td><td>-</td><td>Нет</td><td></td><td>Участвует</td></tr>"
    )
    return (
        "<html><body><p>Бюджетных мест: 72</p>"
        f"<table><tbody>{row_main}{row_quota}</tbody></table></body></html>"
    )


async def test_leti_parser():
    uni = make_university(
        "LETI",
        "https://abit.etu.ru/ru/postupayushhim/lists/page/list",
        [make_major("11.03.02", external_id="uuid-1")],
    )
    parser = LetiParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["id"] == "uuid-1"
        assert "abit.etu.ru" in request.headers["Referer"]
        return httpx.Response(200, text=_leti_html())

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "success"
    major = result.majors[0]
    assert major.summary.places == 72
    # Строка «Особая квота» отфильтрована.
    assert major.summary.applications == 1
    assert major.summary.agreements == 1
    first = major.applicants[0]
    assert first.applicant_code == "3334445"
    assert first.total_score == 265
    assert first.exam_score == 255
    assert first.achievement_score == 10


# ------------------------------------------------------------------ МЭИ --


def _mpei_html() -> str:
    row = (
        '<tr id="p1">'
        "<td>4445556</td><td>270</td><td>260</td><td>90</td><td>85</td><td>85</td>"
        "<td>10</td><td>нет</td><td>нет</td><td>да</td><td>1</td>"
        "<td>да</td><td>нет</td><td>нет</td><td></td>"
        "</tr>"
    )
    return (
        "<html><body><div class='title1'>Количество вакантных мест: 100</div>"
        f'<table class="concurs-list">{row}</table></body></html>'
    )


async def test_mpei_parser():
    uni = make_university(
        "MPEI",
        "https://pk.mpei.ru/info/entrants_list.html",
        [make_major("01.03.02", external_id="entrants_list16.html")],
    )
    parser = MpeiParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/info/entrants_list16.html"
        return httpx.Response(200, text=_mpei_html())

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "success"
    major = result.majors[0]
    assert major.summary.places == 100
    assert major.summary.applications == 1
    assert major.summary.agreements == 1
    first = major.applicants[0]
    assert first.applicant_code == "4445556"
    assert first.total_score == 270
    assert first.exam_score == 260
    assert first.priority == 1


# ---------------------------------------------------------------- СПбАУ --


def _spbau_xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active

    def pad(values: list) -> list:
        return values + [None] * (25 - len(values))

    ws.append(pad([None, "Конкурсная группа:", "03.03.01_бюджет"]))
    ws.append(pad([None, "Форма обучения:", "Очная"]))
    ws.append(pad([None, "Категория:", "Общий конкурс"]))
    ws.append(pad([None, "План приема:", 56]))
    # Строка данных: rank, -, УИД ЕПГУ, -, приоритет, ... баллы ... согласия.
    row = [None] * 25
    row[0] = "1"
    row[2] = "1234567890"
    row[4] = 1
    row[10] = 240
    row[11] = 10
    row[13] = 250
    row[14] = ""
    row[17] = "Нет"
    row[18] = "Нет"
    row[19] = "Да"
    row[20] = "Нет"
    row[24] = ""
    ws.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def test_spbau_parser():
    page_html = (
        "<html><body><table><tr><td>"
        '<a href="/images/documents/campaign/bachelor/lists/B0807.xlsx">Основной конкурс</a>'
        "</td></tr></table></body></html>"
    )
    xlsx_bytes = _spbau_xlsx()

    uni = make_university(
        "SPBAU",
        "https://www.spbau.ru/campaign/bachelor/documents",
        [make_major("03.03.01")],
    )
    parser = SpbauParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".xlsx"):
            return httpx.Response(200, content=xlsx_bytes)
        return httpx.Response(200, text=page_html)

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "success"
    major = result.majors[0]
    assert major.summary.places == 56
    assert major.summary.applications == 1
    assert major.summary.agreements == 1
    first = major.applicants[0]
    assert first.applicant_code == "1234567890"
    assert first.total_score == 250
    assert first.exam_score == 240
    assert first.achievement_score == 10


# ------------------------------------------------------------------ КФУ --


def _kpfu_select_html() -> str:
    return (
        "<html><body><form>"
        '<select name="p_speciality">'
        '<option value="">Все</option>'
        '<option value="123">01.03.02 Прикладная математика и информатика</option>'
        '<option value="456">01.03.02 Прикладная математика (для иностранных граждан)</option>'
        "</select></form></body></html>"
    )


def _kpfu_list_html() -> str:
    row = (
        "<tr><td>1</td><td>6667778</td><td>90</td><td>85</td>"
        "<td>10</td><td>250</td><td>ЕГЭ</td><td>нет</td>"
        "<td>1</td><td>да</td><td>Подано</td><td></td></tr>"
    )
    return (
        "<html><body>"
        '<div class="listing-abitur__plan">План приема: 71</div>'
        '<section class="listing-abitur__section">'
        "<h2>Список поступающих на основные места в рамках контрольных цифр</h2>"
        f'<table class="tablebig"><tbody>{row}</tbody></table>'
        "</section></body></html>"
    )


async def test_kpfu_parser():
    uni = make_university(
        "KPFU",
        "https://kpfu.ru/computing-technology/abiturientam/application",
        [make_major("01.03.02", external_id="9")],
    )
    parser = KpfuParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "abiturient.kpfu.ru"
        # Первый запрос — без p_speciality (резолвим id программы),
        # второй — с p_speciality (сам список). Ответы в cp1251.
        if "p_speciality" not in request.url.params:
            return httpx.Response(200, content=_kpfu_select_html().encode("cp1251"))
        assert request.url.params["p_speciality"] == "123"
        return httpx.Response(200, content=_kpfu_list_html().encode("cp1251"))

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "success"
    major = result.majors[0]
    assert major.internal_id == 123  # выбрана программа для граждан РФ
    assert major.summary.places == 71
    assert major.summary.applications == 1
    assert major.summary.agreements == 1
    first = major.applicants[0]
    assert first.applicant_code == "6667778"
    assert first.total_score == 250
    assert first.achievement_score == 10
    assert first.priority == 1


# ----------------------------------------------------------------- ГУАП --


def _guap_index_html() -> str:
    return (
        "<html><body>"
        '<table id="tablestat"><thead><tr>'
        "<th>Код</th><th>Направление</th><th>Основные места (федеральный бюджет)</th>"
        "</tr></thead><tbody>"
        '<tr><td>09.03.01</td><td>ИВТ</td>'
        '<td><a href="/bach/lists/list_1_75_1_1_1_f_1">683</a></td></tr>'
        "</tbody></table></body></html>"
    )


def _guap_list_html() -> str:
    row = (
        "<tr><td>1</td><td>7778889</td><td>1</td><td>260</td><td>250</td>"
        "<td>10</td><td>90+80+80</td><td>Да</td><td>Нет</td><td>Нет</td><td>Нет</td></tr>"
    )
    return (
        "<html><body>"
        "<h3>Количество мест за вычетом квот - 11</h3>"
        "<p><b>Дата актуализации - </b> 10.07.2026 21:37</p>"
        f'<table class="pk-ratings-table">{row}</table>'
        "</body></html>"
    )


async def test_guap_parser():
    uni = make_university(
        "GUAP",
        "https://priem.guap.ru/bach/lists/list_1_1_1_1",
        [make_major("09.03.01")],
    )
    parser = GuapParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/bach/lists/list_1_1_1_1":
            return httpx.Response(200, text=_guap_index_html())
        assert request.url.path == "/bach/lists/list_1_75_1_1_1_f_1"
        return httpx.Response(200, text=_guap_list_html())

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "success"
    major = result.majors[0]
    assert major.summary.places == 11
    assert major.summary.applications == 1
    assert major.summary.agreements == 1
    assert major.summary.list_formed_at == "10.07.2026 21:37"
    first = major.applicants[0]
    assert first.applicant_code == "7778889"
    assert first.total_score == 260
    assert first.exam_score == 250
    assert first.achievement_score == 10


# --------------------------------------------------------------- Горный --


def _spmi_html() -> str:
    plus = '<i class="fas fa-plus"></i>'
    row = (
        f"<tr><td>1</td><td>8889990</td><td>255</td><td>245</td><td>10</td><td>1</td>"
        f"<td>{plus}</td><td></td><td></td><td></td><td>{plus}</td><td>Участвует</td><td></td></tr>"
    )
    return (
        "<html><body>"
        "<p>Количество мест (квота) за счет бюджета Университета ВСЕГО – "
        '<span class="badge">75</span></p>'
        "<p>особая квота - <span>7</span></p>"
        "<p>отдельная квота - <span>7</span></p>"
        "<p>целевая квота - <span>10</span></p>"
        f'<table class="table-list"><tbody>{row}</tbody></table>'
        "</body></html>"
    )


async def test_spmi_parser_with_cache():
    # Два кода направления делят один specialization_id -> один HTTP-запрос.
    uni = make_university(
        "SPMI",
        "https://priem2026.spmi.ru/specialization?direction_id=7",
        [
            make_major("09.03.01", external_id="13580"),
            make_major("09.03.02", external_id="13580"),
        ],
    )
    parser = SpmiParser(uni, request_delay_seconds=0)

    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        assert request.url.params["specialization_id"] == "13580"
        assert request.url.params["applicant_type_id"] == "2"
        return httpx.Response(200, text=_spmi_html())

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "success"
    assert len(result.majors) == 2
    assert calls["count"] == 1  # кэш по specialization_id
    major = result.majors[0]
    assert major.summary.places == 51  # 75 - 7 - 7 - 10
    assert major.summary.applications == 1
    assert major.summary.agreements == 1
    first = major.applicants[0]
    assert first.applicant_code == "8889990"
    assert first.total_score == 255
    assert first.exam_score == 245


# ------------------------------------------------------------------ ВШЭ --

_HSE_SET = "set-uuid-1"
_HSE_GROUP = "group-uuid-1"


def _hse_header(filial: str = "Москва", place_code: str = "Б") -> dict:
    return {
        "competitiveGroup": "Физика (О Б)",
        "eduForm": "Очная",
        "educationProgram": "Физика",
        "filial": filial,
        "placeCount": 32,
        "placeType": {"id": "pt-budget", "code": place_code, "name": "Бюджетные места"},
        "updatedAt": "12.07.2026 16:02",
    }


def _hse_row(code: str, total: float, agreement: bool = False, bvi: bool = False) -> dict:
    return {
        "idEpgu": code,
        "sumCompetitiveScore": total,
        "sumEntranceTestScore": total - 10,
        "achievementsSum": 10.0,
        "achivementsSumTarget": 0,
        "isWithoutExamsAdmReasonBool": bvi,
        "isConcertToEnrollment": agreement,
        "isHasPrerogativeRight9": False,
        "isHasPrerogativeRight10": True,
        "priority": 1,
        "participantStatus": "Участвует в конкурсе",
    }


async def test_hse_parser_paginates_and_checks_campus():
    uni = make_university(
        "HSE_MSK",
        "https://pk.hse.ru/admissions/bak/BD/applicants",
        [make_major("03.03.02", external_id=f"{_HSE_SET}/{_HSE_GROUP}")],
    )
    parser = HseParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/competitve-group/{_HSE_GROUP}"):
            return httpx.Response(200, json=_hse_header())
        assert request.url.path.endswith("/applicant")
        assert request.url.params["setOfCompetitiveGroupId"] == _HSE_SET
        assert request.url.params["placeType"] == "pt-budget"
        assert request.url.params["level"] == "BAK"
        page = int(request.url.params["page"])
        # Две страницы по две записи (пагинация Spring Page).
        content = {
            0: [_hse_row("111", 296.0, agreement=True, bvi=True), _hse_row("222", 280.0)],
            1: [_hse_row("333", 250.0)],
        }[page]
        return httpx.Response(200, json={"content": content, "totalPages": 2})

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "success"
    major = result.majors[0]
    assert major.summary.places == 32
    assert major.summary.applications == 3  # обе страницы собраны
    assert major.summary.agreements == 1
    assert major.summary.list_formed_at == "12.07.2026 16:02"
    first = major.applicants[0]
    assert first.applicant_code == "111"
    assert first.total_score == 296
    assert first.exam_score == 286
    assert first.achievement_score == 10
    assert first.is_bvi is True
    assert first.preferential_right == "Да"


async def test_hse_parser_rejects_wrong_campus():
    """URL чужого кампуса (СПб для HSE_MSK) даёт явную ошибку, а не чужие данные."""
    uni = make_university(
        "HSE_MSK",
        "https://pk.hse.ru/admissions/bak/BD/applicants",
        [make_major("03.03.02", external_id=f"{_HSE_SET}/{_HSE_GROUP}")],
    )
    parser = HseParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_hse_header(filial="Санкт-Петербург"))

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "failed"
    assert "кампус" in result.errors[0]


async def test_hse_parser_rejects_mismatched_list_type():
    """Бюджетное направление с платным groupId (К) падает с понятной ошибкой."""
    uni = make_university(
        "HSE_MSK",
        "https://pk.hse.ru/admissions/bak/BD/applicants",
        [make_major("03.03.02", external_id=f"{_HSE_SET}/{_HSE_GROUP}")],
    )
    parser = HseParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_hse_header(place_code="К"))

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "failed"
    assert "тип списка не совпадает" in result.errors[0]


async def test_hse_parser_paid_major_parses_paid_list():
    """Направление с finance_type=Контракт парсит платный список (placeType К)."""
    uni = make_university(
        "HSE_MSK",
        "https://pk.hse.ru/admissions/bak/BD/applicants",
        [
            make_major(
                "03.03.02-К",
                name="Физика (платное)",
                external_id=f"{_HSE_SET}/{_HSE_GROUP}",
                finance_type="Контракт",
            )
        ],
    )
    parser = HseParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/competitve-group/{_HSE_GROUP}"):
            return httpx.Response(200, json=_hse_header(place_code="К"))
        return httpx.Response(
            200, json={"content": [_hse_row("777", 240.0)], "totalPages": 1}
        )

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "success"
    major = result.majors[0]
    assert major.code == "03.03.02-К"
    assert major.summary.applications == 1
    assert major.applicants[0].applicant_code == "777"


# ------------------------------------------------- Общее поведение базы --


async def test_http_parser_partial_on_major_error():
    """Ошибка одного направления не роняет запуск: статус partial."""
    uni = make_university(
        "MPEI",
        "https://pk.mpei.ru/info/entrants_list.html",
        [
            make_major("01.03.02", external_id="entrants_list16.html"),
            make_major("09.03.01", external_id="entrants_list14.html"),
        ],
    )
    parser = MpeiParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("entrants_list16.html"):
            return httpx.Response(200, text=_mpei_html())
        return httpx.Response(500)

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "partial"
    assert len(result.majors) == 1
    assert len(result.errors) == 1
    assert "09.03.01" in result.errors[0]


async def test_http_parser_failed_on_prepare_error():
    """Падение подготовки (сводной страницы) даёт статус failed."""
    uni = make_university(
        "GUAP",
        "https://priem.guap.ru/bach/lists/list_1_1_1_1",
        [make_major("09.03.01")],
    )
    parser = GuapParser(uni, request_delay_seconds=0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    mock_client(parser, handler)
    result = await parser.parse()

    assert result.status == "failed"
    assert result.majors == []
    assert result.errors
