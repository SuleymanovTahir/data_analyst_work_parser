#!/usr/bin/env python3
"""
HH.ru Smart Vacancy Bot v2
===========================
Полноценный Telegram-бот для поиска вакансий на hh.ru.
Настройка поиска прямо через Telegram — без редактирования кода.

Команды:
  /menu      — главное меню
  /start     — приветствие и помощь
  /new       — создать новый сценарий (wizard)
  /templates — список сохранённых сценариев, выбор/редактирование/удаление
  /current   — показать активный сценарий
  /run       — запустить поиск прямо сейчас (не ждать таймер)
  /preview   — предпросмотр без сохранения истории
  /reset_sent — сброс истории отправок активного сценария
  /toggle    — включить/выключить автопоиск
  /status    — текущий статус и статистика

Запуск: python3 hh_vacancy_bot.py
"""

import base64
import gzip
import requests
import json
import time
import uuid
import re
import html
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse
except Exception:
    FastAPI = None
    Request = None
    HTMLResponse = None
    JSONResponse = None

try:
    from vercel.functions import RuntimeCache
except Exception:
    RuntimeCache = None

# ═══════════════════════════════════════════════════════════
#  КОНФИГ
# ═══════════════════════════════════════════════════════════

IS_VERCEL = bool(os.getenv("VERCEL") or os.getenv("VERCEL_ENV"))

if IS_VERCEL:
    BOT_TOKEN = os.getenv("HH_TELEGRAM_BOT_TOKEN", "").strip()
    WEBHOOK_URL = os.getenv("HH_TELEGRAM_WEBHOOK_URL", "").strip()
    WEBHOOK_HOST = os.getenv("HH_TELEGRAM_WEBHOOK_HOST", "0.0.0.0").strip() or "0.0.0.0"
    WEBHOOK_PORT = int(os.getenv("HH_TELEGRAM_WEBHOOK_PORT", "8080") or 8080)
else:
    try:
        from bot_local_config import BOT_TOKEN, WEBHOOK_URL, WEBHOOK_HOST, WEBHOOK_PORT
    except Exception:
        BOT_TOKEN = os.getenv("HH_TELEGRAM_BOT_TOKEN", "").strip()
        WEBHOOK_URL = os.getenv("HH_TELEGRAM_WEBHOOK_URL", "").strip()
        WEBHOOK_HOST = os.getenv("HH_TELEGRAM_WEBHOOK_HOST", "0.0.0.0").strip() or "0.0.0.0"
        WEBHOOK_PORT = int(os.getenv("HH_TELEGRAM_WEBHOOK_PORT", "8080") or 8080)

WEBHOOK_URL = (WEBHOOK_URL or "").strip().rstrip("/")
WEBHOOK_HOST = (WEBHOOK_HOST or "0.0.0.0").strip() or "0.0.0.0"
WEBHOOK_PORT = int(WEBHOOK_PORT or 8080)
USE_WEBHOOK = bool(WEBHOOK_URL)
CRON_SECRET = (os.getenv("CRON_SECRET") or os.getenv("HH_CRON_SECRET") or "").strip()
WEB_ADMIN_TOKEN = (os.getenv("HH_WEB_ADMIN_TOKEN") or "").strip()
STATE_TTL_SECONDS = int(os.getenv("HH_STATE_TTL_SECONDS", str(60 * 60 * 24 * 30)) or (60 * 60 * 24 * 30))
AREAS_TTL_SECONDS = int(os.getenv("HH_AREAS_TTL_SECONDS", str(60 * 60 * 24 * 30)) or (60 * 60 * 24 * 30))

DATA_FILE = os.path.join(tempfile.gettempdir(), "bot_data.json") if IS_VERCEL else "bot_data.json"
AREAS_CACHE = os.path.join(tempfile.gettempdir(), "areas_cache.json") if IS_VERCEL else "areas_cache.json"

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
HH_API = "https://api.hh.ru"

STATE_CACHE_KEY = "bot_data"
AREAS_CACHE_KEY = "areas_tree_gzip"
DICTS_CACHE_KEY = "hh_dictionaries"

_runtime_cache = None
if IS_VERCEL and RuntimeCache is not None:
    try:
        _runtime_cache = RuntimeCache(namespace="hh_vacancy_bot")
    except Exception as e:
        print(f"⚠️ Runtime Cache недоступен: {e}")

# ─── HH.ru опции ────────────────────────────────────────────
ANY_EXPERIENCE = "any"

EXPERIENCE_OPTIONS = {
    ANY_EXPERIENCE: "Не имеет значения",
    "noExperience": "Без опыта",
    "between1And3": "1–3 года",
    "between3And6": "3–6 лет",
    "moreThan6":    "Более 6 лет",
}

SORT_OPTIONS = {
    "publication_time": "По дате размещения",
    "relevance":        "По релевантности / совпадению",
    "match_desc":       "По совпадению с запросом",
    "name_asc":         "По названию",
    "salary_desc":      "По зарплате (убыв.)",
    "salary_asc":       "По зарплате (возр.)",
}

API_SORT_OPTIONS = {"publication_time", "relevance", "salary_desc", "salary_asc"}

SEARCH_FIELD_OPTIONS = {
    "name":         "Название вакансии",
    "company_name": "Компания",
    "description":  "Описание",
}

INTERVAL_OPTIONS = {
    15:  "15 мин",
    30:  "30 мин",
    60:  "1 час",
    120: "2 часа",
    240: "4 часа",
}

MAX_PAGES_OPTIONS = {
    1:  "1 страница",
    3:  "3 страницы",
    5:  "5 страниц",
    10: "10 страниц",
}

PERIOD_OPTIONS = {
    1:  "За 1 день",
    3:  "За 3 дня",
    7:  "За 7 дней",
    14: "За 14 дней",
    30: "За 30 дней",
}

MAX_RESULTS_OPTIONS = {
    20:  "20 вакансий",
    50:  "50 вакансий",
    100: "100 вакансий",
    200: "200 вакансий",
}

PAGE_SIZE_OPTIONS = {
    5:  "5 вакансий",
    10: "10 вакансий",
    15: "15 вакансий",
}

SKIP_WORDS = {"нет", "no", "none", "-", "skip"}

RUSSIA_AREA_ID = 113
MOSCOW_AREA_ID = 1

# ─── Популярные страны/регионы для примеров в wizard ──────
POPULAR_AREA_NAMES = [
    "Беларусь", "Казахстан", "Грузия", "Армения", "Азербайджан", "Узбекистан",
    "Кыргызстан", "Сербия", "Германия", "Польша", "Кипр", "Турция",
    "ОАЭ", "Израиль", "Латвия", "Литва", "Эстония", "Финляндия",
]

# ─── Ключевые слова для фильтрации гемблинга ──────────────
DEFAULT_EXCLUDE_KEYWORDS = [
    # Английские
    "igaming", "i-gaming", "i gaming", "gaming", "gambl", "casino",
    "betting", "sportsbook", "lottery", "bingo", "poker", "slot",
    "esports", "e-sports", "cyber sport", "online casino", "live casino",
    "jackpot", "roulette", "blackjack", "wager", "bookmaker", "freebet",
    "freespin", "sportsbet", "sportbet", "1xbet", "betway", "melbet",
    "winline", "fonbet", "mostbet", "parimatch", "william hill", "bet365",
    "betfair", "pinnacle", "unibet", "bwin", "888casino", "playtech",
    "microgaming", "netent", "evolution gaming", "gamedev", "game dev",
    "gamification", "slot game", "slot games", "casino game", "casino games",
    "sports betting", "bet", "odds", "affiliate manager", "affiliate traffic",
    "ua manager", "user acquisition manager", "traffic manager", "p2e",
    "web3 casino", "crypto casino", "sweepstake", "sweepstakes",
    # Русские
    "казино", "гэмблинг", "гэмбл", "ставки", "ставках",
    "букмекер", "покер", "слоты", "азартн", "онлайн-казино",
    "игорн", "тотализатор", "киберспорт", "лотерея", "бинго",
    "джекпот", "рулетка", "блэкджек", "фриспины", "фрибет",
    "ставка на спорт", "букмекерская", "пари матч", "леон бет",
    "форбет", "мостбет", "мелбет", "арбитраж трафика", "трафик-менеджер",
    "медиабайер", "байер трафика", "геминг", "гейминг", "игровая индустрия",
    "игровые автоматы", "беттинг", "букмекерская компания",
]

# ─── Дефолтные поисковые запросы ─────────────────────────
DEFAULT_QUERIES = [
    # Data / Product
    "data analyst", "product analyst", "product/data analyst",
    "product data analyst", "data/product analyst",
    # Business & Systems
    "business analyst", "systems analyst", "system analyst", "web analyst",
    # Science & Engineering
    "data scientist", "data engineer", "analytics engineer", "bi analyst",
    # BI & Reporting
    "business intelligence analyst", "reporting analyst", "bi developer",
    # Marketing / Growth / Finance / Risk
    "marketing analyst", "growth analyst", "financial analyst",
    "finance analyst", "risk analyst", "quantitative analyst", "quant analyst",
    "fraud analyst", "antifraud analyst", "market analyst", "research analyst",
    # Research & UX
    "ux researcher", "product researcher",
    # Русские варианты
    "аналитик данных", "продуктовый аналитик", "аналитик продукта",
    "product / data analyst",
    "бизнес аналитик", "бизнес-аналитик",
    "системный аналитик", "маркетинговый аналитик", "финансовый аналитик",
    "аналитик", "дата аналитик", "bi аналитик", "продуктовый/bi аналитик",
    "веб-аналитик", "аналитик продукта и данных", "аналитик бизнес-процессов",
]


# ═══════════════════════════════════════════════════════════
#  ХРАНИЛИЩЕ ДАННЫХ
# ═══════════════════════════════════════════════════════════

def ensure_bot_token():
    if BOT_TOKEN:
        return BOT_TOKEN
    raise RuntimeError(
        "Не найден BOT_TOKEN. Укажите его в файле bot_local_config.py "
        "или в переменной окружения HH_TELEGRAM_BOT_TOKEN."
    )


def _runtime_cache_available():
    return _runtime_cache is not None


def _cache_get(key):
    if not _runtime_cache_available():
        return None
    try:
        return _runtime_cache.get(key)
    except Exception as e:
        print(f"⚠️ Ошибка чтения Runtime Cache ({key}): {e}")
        return None


def _cache_set(key, value, ttl_seconds, tags=None):
    if not _runtime_cache_available():
        return False
    try:
        options = {"ttl": int(ttl_seconds)}
        if tags:
            options["tags"] = list(tags)
        _runtime_cache.set(key, value, options)
        return True
    except Exception as e:
        print(f"⚠️ Ошибка записи Runtime Cache ({key}): {e}")
        return False


def _pack_json(value):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, compresslevel=6)).decode("ascii")


def _unpack_json(payload):
    if payload is None:
        return None
    if isinstance(payload, (dict, list)):
        return payload
    raw = gzip.decompress(base64.b64decode(str(payload).encode("ascii")))
    return json.loads(raw.decode("utf-8"))

def load_data():
    cached = _cache_get(STATE_CACHE_KEY)
    if cached is not None:
        normalized = _normalize_data(cached)
        if _ensure_templates_ready(normalized):
            save_data(normalized)
        return normalized

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {
            "chat_id":            None,
            "templates":          [],
            "active_template_id": None,
            "searching":          False,
            "sent_ids":           [],
            "sent_ids_by_template": {},
            "last_check":         0,
            "user_states":        {},
            "result_sessions":    {},
        }
    normalized = _normalize_data(data)
    if _ensure_templates_ready(normalized):
        save_data(normalized)
        return normalized
    _cache_set(STATE_CACHE_KEY, normalized, STATE_TTL_SECONDS, tags=["bot-state"])
    return normalized

def save_data(data):
    sent_ids_by_template = {}
    for template_id, values in (data.get("sent_ids_by_template", {}) or {}).items():
        sent_ids_by_template[str(template_id)] = list(values or [])[-10000:]

    all_sent_ids = []
    seen_ids = set()
    for values in sent_ids_by_template.values():
        for vacancy_id in reversed(values):
            if vacancy_id in seen_ids:
                continue
            seen_ids.add(vacancy_id)
            all_sent_ids.append(vacancy_id)
    all_sent_ids = list(reversed(all_sent_ids[-10000:]))

    data["sent_ids_by_template"] = sent_ids_by_template
    data["sent_ids"] = all_sent_ids
    if _cache_set(STATE_CACHE_KEY, data, STATE_TTL_SECONDS, tags=["bot-state"]):
        return
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _unique_list(values):
    seen = set()
    result = []
    for value in values or []:
        if value is None:
            continue
        value = str(value).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _normalize_template(template):
    tmpl = dict(template or {})

    old_area_mode = tmpl.get("area_mode", "exclude_russia")
    old_area_ids = [str(x) for x in tmpl.get("area_ids", [])]
    old_area_names = tmpl.get("area_names", []) or []

    included_ids = tmpl.get("included_area_ids")
    included_names = tmpl.get("included_area_names")
    excluded_ids = tmpl.get("excluded_area_ids")
    excluded_names = tmpl.get("excluded_area_names")

    if included_ids is None and excluded_ids is None:
        if old_area_mode == "include_areas":
            included_ids = old_area_ids
            included_names = old_area_names
            excluded_ids = []
            excluded_names = []
        elif old_area_mode == "exclude_areas":
            included_ids = []
            included_names = []
            excluded_ids = old_area_ids
            excluded_names = old_area_names
        else:
            included_ids = []
            included_names = []
            excluded_ids = [str(RUSSIA_AREA_ID)]
            excluded_names = ["Россия"]

    tmpl["queries"] = [q.strip() for q in tmpl.get("queries", DEFAULT_QUERIES) if q and q.strip()]
    tmpl["queries"] = tmpl["queries"] or DEFAULT_QUERIES[:]

    tmpl["experience"] = _unique_list(tmpl.get("experience", [ANY_EXPERIENCE]))
    if not tmpl["experience"]:
        tmpl["experience"] = [ANY_EXPERIENCE]

    tmpl["search_fields"] = _unique_list(tmpl.get("search_fields", ["name", "company_name", "description"]))
    if not tmpl["search_fields"]:
        tmpl["search_fields"] = ["name", "company_name", "description"]

    tmpl["included_area_ids"] = _unique_list(included_ids or [])
    tmpl["included_area_names"] = [n.strip() for n in (included_names or []) if n and n.strip()]
    tmpl["excluded_area_ids"] = _unique_list(excluded_ids or [])
    tmpl["excluded_area_names"] = [n.strip() for n in (excluded_names or []) if n and n.strip()]

    tmpl["exclude_keywords"] = [k.strip().lower() for k in tmpl.get("exclude_keywords", DEFAULT_EXCLUDE_KEYWORDS) if k and k.strip()]
    tmpl["include_keywords"] = [k.strip().lower() for k in tmpl.get("include_keywords", []) if k and k.strip()]
    tmpl["include_in"] = tmpl.get("include_in", "both")
    tmpl["exclude_in"] = tmpl.get("exclude_in", "both")
    tmpl["work_formats"] = _unique_list(tmpl.get("work_formats", []))
    tmpl["employment_types"] = _unique_list(tmpl.get("employment_types", []))
    tmpl["period_days"] = int(tmpl.get("period_days", 1) or 1)
    tmpl["only_with_salary"] = bool(tmpl.get("only_with_salary", False))
    tmpl["salary_min"] = max(0, int(tmpl.get("salary_min", 0) or 0))
    tmpl["excluded_employers"] = [k.strip().lower() for k in tmpl.get("excluded_employers", []) if k and k.strip()]
    tmpl["max_results"] = max(1, int(tmpl.get("max_results", 50) or 50))
    tmpl["delivery_page_size"] = max(1, int(tmpl.get("delivery_page_size", 5) or 5))
    tmpl["sort"] = tmpl.get("sort", "publication_time")
    tmpl["interval"] = int(tmpl.get("interval", 30) or 30)
    tmpl["max_pages"] = int(tmpl.get("max_pages", 5) or 5)
    tmpl["name"] = (tmpl.get("name") or "Новый сценарий")[:50]
    tmpl["id"] = str(tmpl.get("id") or str(uuid.uuid4())[:8])

    if tmpl["id"] == "default01":
        excluded_ids = tmpl.get("excluded_area_ids", [])
        if excluded_ids == [str(MOSCOW_AREA_ID)]:
            tmpl["name"] = "Аналитик — все страны кроме России"
            tmpl["excluded_area_ids"] = [str(RUSSIA_AREA_ID)]
            tmpl["excluded_area_names"] = ["Россия"]

    return tmpl


def _normalize_data(data):
    sent_ids_by_template = data.get("sent_ids_by_template", {}) or {}
    normalized_sent_map = {}
    for template_id, values in sent_ids_by_template.items():
        normalized_sent_map[str(template_id)] = list(values or [])[-10000:]

    legacy_sent_ids = list(data.get("sent_ids", []))
    active_template_id = data.get("active_template_id")
    if legacy_sent_ids and active_template_id and str(active_template_id) not in normalized_sent_map:
        normalized_sent_map[str(active_template_id)] = legacy_sent_ids[-10000:]

    normalized = {
        "chat_id":            data.get("chat_id"),
        "templates":          [_normalize_template(t) for t in data.get("templates", [])],
        "active_template_id": data.get("active_template_id"),
        "searching":          bool(data.get("searching", False)),
        "sent_ids":           list(data.get("sent_ids", [])),
        "sent_ids_by_template": normalized_sent_map,
        "last_check":         data.get("last_check", 0),
        "user_states":        data.get("user_states", {}),
        "result_sessions":    data.get("result_sessions", {}) or {},
    }

    state_map = normalized["user_states"]
    for chat_id, state in list(state_map.items()):
        if not isinstance(state, dict):
            state_map.pop(chat_id, None)
            continue
        if "draft" in state:
            state["draft"] = _normalize_template(state.get("draft", {}))
        history = state.get("history")
        if not isinstance(history, list):
            state["history"] = []

    result_sessions = normalized["result_sessions"]
    for session_id, session in list(result_sessions.items()):
        if not isinstance(session, dict):
            result_sessions.pop(session_id, None)
            continue
        vacancies = session.get("vacancies")
        if not isinstance(vacancies, list):
            result_sessions.pop(session_id, None)
            continue
        session["page_size"] = max(1, int(session.get("page_size", 5) or 5))
        session["current_page"] = max(0, int(session.get("current_page", 0) or 0))
        session["template_name"] = str(session.get("template_name") or "Поиск")
        session["mode"] = "preview" if session.get("mode") == "preview" else "run"
        session["errors"] = [str(item) for item in (session.get("errors") or []) if str(item).strip()]

    return normalized


def _template_sent_ids(data, template_id):
    template_id = str(template_id or "")
    return list((data.get("sent_ids_by_template", {}) or {}).get(template_id, []))


def _set_template_sent_ids(data, template_id, vacancy_ids):
    template_id = str(template_id or "")
    sent_map = data.setdefault("sent_ids_by_template", {})
    sent_map[template_id] = list(vacancy_ids or [])[-10000:]


def _ensure_templates_ready(data):
    changed = False
    templates = data.get("templates", [])

    if not templates:
        tmpl = _create_default_template()
        data["templates"] = [tmpl]
        data["active_template_id"] = tmpl["id"]
        _set_template_sent_ids(data, tmpl["id"], [])
        changed = True
    elif not data.get("active_template_id"):
        data["active_template_id"] = templates[0]["id"]
        changed = True

    return changed


def _esc(value):
    return html.escape(str(value or ""), quote=True)


def _short_label(text, max_len=22):
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "…"


def _back_home_row(back_callback=None):
    row = []
    if back_callback:
        row.append({"text": "Назад", "callback_data": back_callback})
    row.append({"text": "Главное меню", "callback_data": "menu_home"})
    return [row]


def _wizard_move_to(state, next_step):
    current_step = state.get("step")
    if current_step and current_step != next_step:
        history = state.setdefault("history", [])
        history.append(current_step)
    state["step"] = next_step


def _result_session_page_count(session):
    vacancies = session.get("vacancies", [])
    page_size = max(1, int(session.get("page_size", 5) or 5))
    return max(1, (len(vacancies) + page_size - 1) // page_size)


def _trim_result_sessions(data):
    sessions = data.setdefault("result_sessions", {})
    ordered = sorted(
        sessions.items(),
        key=lambda item: float((item[1] or {}).get("created_at", 0) or 0),
        reverse=True,
    )
    keep_ids = {session_id for session_id, _ in ordered[:6]}
    for session_id in list(sessions.keys()):
        if session_id not in keep_ids:
            sessions.pop(session_id, None)


def _split_text_values(value):
    if value is None:
        return []
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = re.split(r"[\n,;]+", str(value))
    return [str(item).strip() for item in raw_values if str(item).strip()]


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on", "да", "вкл"}


def _coerce_int(value, default=0, min_value=None, max_value=None):
    try:
        result = int(value)
    except Exception:
        result = int(default)
    if min_value is not None:
        result = max(min_value, result)
    if max_value is not None:
        result = min(max_value, result)
    return result


def _strip_hh_highlight(text):
    clean = re.sub(r"</?highlighttext>", "", str(text or ""), flags=re.IGNORECASE)
    return " ".join(clean.split())


def _option_list(options_map):
    return [{"id": str(code), "label": str(label)} for code, label in options_map.items()]


def _vacancy_to_web_item(vacancy):
    return {
        "id": str(vacancy.get("id") or ""),
        "name": str(vacancy.get("name") or "Без названия"),
        "employer": str((vacancy.get("employer") or {}).get("name") or "Компания не указана"),
        "area": str((vacancy.get("area") or {}).get("name") or "Локация не указана"),
        "experience": str((vacancy.get("experience") or {}).get("name") or "Не указан"),
        "salary": _vacancy_salary_text(vacancy),
        "schedule": str((vacancy.get("schedule") or {}).get("name") or ""),
        "work_formats": [
            str((item or {}).get("name") or "")
            for item in (vacancy.get("work_format") or [])
            if (item or {}).get("name")
        ],
        "url": str(vacancy.get("alternate_url") or ""),
        "published_at": str(_publication_key(vacancy) or ""),
        "snippet": _strip_hh_highlight((vacancy.get("snippet") or {}).get("requirement") or ""),
    }


def _template_to_web_payload(template):
    tmpl = _normalize_template(template)
    return {
        "id": tmpl["id"],
        "name": tmpl["name"],
        "queries": list(tmpl.get("queries", [])),
        "search_fields": list(tmpl.get("search_fields", [])),
        "experience": list(tmpl.get("experience", [])),
        "included_area_names": list(tmpl.get("included_area_names", [])),
        "excluded_area_names": list(tmpl.get("excluded_area_names", [])),
        "include_keywords": list(tmpl.get("include_keywords", [])),
        "include_in": tmpl.get("include_in", "both"),
        "exclude_keywords": list(tmpl.get("exclude_keywords", [])),
        "exclude_in": tmpl.get("exclude_in", "both"),
        "work_formats": list(tmpl.get("work_formats", [])),
        "employment_types": list(tmpl.get("employment_types", [])),
        "only_with_salary": bool(tmpl.get("only_with_salary", False)),
        "salary_min": int(tmpl.get("salary_min", 0) or 0),
        "excluded_employers": list(tmpl.get("excluded_employers", [])),
        "sort": tmpl.get("sort", "publication_time"),
        "period_days": int(tmpl.get("period_days", 1) or 1),
        "max_pages": int(tmpl.get("max_pages", 5) or 5),
        "max_results": int(tmpl.get("max_results", 50) or 50),
        "delivery_page_size": int(tmpl.get("delivery_page_size", 5) or 5),
        "interval": int(tmpl.get("interval", 30) or 30),
        "summary_html": _format_template_summary(tmpl, detailed=True),
    }


def _web_options_payload():
    return {
        "search_fields": _option_list(SEARCH_FIELD_OPTIONS),
        "experience": _option_list(EXPERIENCE_OPTIONS),
        "work_formats": _option_list(get_work_format_options()),
        "employment_types": _option_list(get_employment_options()),
        "sort": _option_list(SORT_OPTIONS),
        "period_days": _option_list(PERIOD_OPTIONS),
        "max_pages": _option_list(MAX_PAGES_OPTIONS),
        "max_results": _option_list(MAX_RESULTS_OPTIONS),
        "page_size": _option_list(PAGE_SIZE_OPTIONS),
        "interval": _option_list(INTERVAL_OPTIONS),
        "popular_areas": list(POPULAR_AREA_NAMES),
    }


def _upsert_template(data, template, activate=False):
    normalized = _normalize_template(template)
    templates = data.setdefault("templates", [])
    replaced = False
    for index, item in enumerate(templates):
        if str(item.get("id")) == normalized["id"]:
            templates[index] = normalized
            replaced = True
            break
    if not replaced:
        templates.append(normalized)
    data.setdefault("sent_ids_by_template", {}).setdefault(normalized["id"], [])
    if activate:
        data["active_template_id"] = normalized["id"]
    return normalized


def _build_template_from_payload(payload):
    payload = dict(payload or {})
    warnings = []

    search_fields_allowed = set(SEARCH_FIELD_OPTIONS.keys())
    experience_allowed = set(EXPERIENCE_OPTIONS.keys())
    work_formats_allowed = set(get_work_format_options().keys())
    employment_allowed = set(get_employment_options().keys())

    queries = _split_text_values(payload.get("queries")) or DEFAULT_QUERIES[:]
    search_fields = [item for item in _unique_list(payload.get("search_fields", [])) if item in search_fields_allowed]
    if not search_fields:
        search_fields = ["name", "company_name", "description"]

    experience = [item for item in _unique_list(payload.get("experience", [])) if item in experience_allowed]
    if ANY_EXPERIENCE in experience or not experience:
        experience = [ANY_EXPERIENCE]

    included_area_names = _split_text_values(payload.get("included_area_names"))
    included_area_ids, included_area_names, not_found_include = _resolve_area_names(included_area_names)
    if not_found_include:
        warnings.append(f"Не распознаны регионы для включения: {', '.join(not_found_include)}")

    excluded_area_names = _split_text_values(payload.get("excluded_area_names"))
    excluded_area_ids, excluded_area_names, not_found_exclude = _resolve_area_names(excluded_area_names)
    if not_found_exclude:
        warnings.append(f"Не распознаны регионы для исключения: {', '.join(not_found_exclude)}")

    work_formats = [item for item in _unique_list(payload.get("work_formats", [])) if item in work_formats_allowed]
    employment_types = [item for item in _unique_list(payload.get("employment_types", [])) if item in employment_allowed]

    sort_code = str(payload.get("sort") or "publication_time")
    if sort_code not in SORT_OPTIONS:
        sort_code = "publication_time"

    include_in = str(payload.get("include_in") or "both")
    if include_in not in {"title", "description", "both"}:
        include_in = "both"

    exclude_in = str(payload.get("exclude_in") or "both")
    if exclude_in not in {"title", "description", "both"}:
        exclude_in = "both"

    template = {
        "id": str(payload.get("id") or str(uuid.uuid4())[:8]),
        "name": str(payload.get("name") or "Новый сценарий").strip()[:50] or "Новый сценарий",
        "queries": queries,
        "search_fields": search_fields,
        "experience": experience,
        "included_area_ids": included_area_ids,
        "included_area_names": included_area_names,
        "excluded_area_ids": excluded_area_ids,
        "excluded_area_names": excluded_area_names,
        "include_keywords": [item.lower() for item in _split_text_values(payload.get("include_keywords"))],
        "include_in": include_in,
        "exclude_keywords": [item.lower() for item in _split_text_values(payload.get("exclude_keywords"))],
        "exclude_in": exclude_in,
        "work_formats": work_formats,
        "employment_types": employment_types,
        "only_with_salary": _coerce_bool(payload.get("only_with_salary")),
        "salary_min": _coerce_int(payload.get("salary_min"), default=0, min_value=0),
        "excluded_employers": [item.lower() for item in _split_text_values(payload.get("excluded_employers"))],
        "sort": sort_code,
        "period_days": _coerce_int(payload.get("period_days"), default=1, min_value=1, max_value=30),
        "max_pages": _coerce_int(payload.get("max_pages"), default=5, min_value=1, max_value=20),
        "max_results": _coerce_int(payload.get("max_results"), default=50, min_value=1, max_value=500),
        "delivery_page_size": _coerce_int(payload.get("delivery_page_size"), default=5, min_value=1, max_value=50),
        "interval": _coerce_int(payload.get("interval"), default=30, min_value=5, max_value=1440),
    }

    return _normalize_template(template), warnings


def _build_web_state(data=None):
    data = load_data() if data is None else _normalize_data(data)
    active = _active_template(data)
    return {
        "status": _build_runtime_status(data),
        "searching": bool(data.get("searching", False)),
        "active_template_id": data.get("active_template_id"),
        "templates": [_template_to_web_payload(item) for item in data.get("templates", [])],
        "active_template": _template_to_web_payload(active) if active else None,
        "new_template": _template_to_web_payload(_new_draft()),
        "options": _web_options_payload(),
    }


# ═══════════════════════════════════════════════════════════
#  TELEGRAM API
# ═══════════════════════════════════════════════════════════

def get_public_base_url(request=None):
    explicit_url = (WEBHOOK_URL or "").strip().rstrip("/")
    if explicit_url:
        return explicit_url
    if request is not None:
        return str(request.base_url).rstrip("/")
    return ""


def get_telegram_webhook_target(request=None):
    base_url = get_public_base_url(request)
    if not base_url:
        return ""
    webhook_path = "/telegram-webhook" if IS_VERCEL else "/api/telegram/webhook"
    return f"{base_url}{webhook_path}"

def tg_call(method, **kwargs):
    if not TG_API:
        print(f"❌ Telegram API недоступен: не задан BOT_TOKEN ({method})")
        return {"ok": False, "description": "BOT_TOKEN missing"}
    try:
        r = requests.post(f"{TG_API}/{method}", json=kwargs, timeout=15)
        return r.json()
    except Exception as e:
        print(f"❌ Telegram API error ({method}): {e}")
        return {}

def send_msg(chat_id, text, reply_markup=None, parse_mode="HTML"):
    payload = {
        "chat_id":                  chat_id,
        "text":                     text,
        "parse_mode":               parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_call("sendMessage", **payload)

def edit_reply_markup(chat_id, message_id, reply_markup):
    tg_call("editMessageReplyMarkup",
            chat_id=chat_id, message_id=message_id,
            reply_markup=reply_markup)


def edit_msg(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_call("editMessageText", **payload)

def answer_cb(cb_id, text=""):
    tg_call("answerCallbackQuery", callback_query_id=cb_id, text=text)

def get_updates(offset=0):
    if not TG_API:
        print("❌ getUpdates недоступен: не задан BOT_TOKEN")
        return []
    try:
        r = requests.post(f"{TG_API}/getUpdates",
                          json={"offset": offset, "timeout": 3, "limit": 20},
                          timeout=10)
        return r.json().get("result", [])
    except Exception:
        return []


def set_webhook(url):
    payload = {
        "url": url,
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": False,
    }
    return tg_call("setWebhook", **payload)


def delete_webhook(drop_pending_updates=False):
    return tg_call("deleteWebhook", drop_pending_updates=drop_pending_updates)


def get_webhook_info():
    return tg_call("getWebhookInfo")


# ═══════════════════════════════════════════════════════════
#  HH.RU AREAS
# ═══════════════════════════════════════════════════════════

_area_tree   = None
_area_by_id  = None
_area_by_name = None
_area_children_cache = {}
_hh_dictionaries = None
_employment_options = None
_work_format_options = None

def get_area_tree():
    global _area_tree
    if _area_tree is not None:
        return _area_tree

    cached_tree = _cache_get(AREAS_CACHE_KEY)
    if cached_tree is not None:
        try:
            _area_tree = _unpack_json(cached_tree)
            return _area_tree
        except Exception as e:
            print(f"⚠️ Не удалось распаковать areas из Runtime Cache: {e}")

    try:
        with open(AREAS_CACHE, "r", encoding="utf-8") as f:
            _area_tree = json.load(f)
            return _area_tree
    except Exception:
        pass
    try:
        r = requests.get(f"{HH_API}/areas", timeout=20)
        r.raise_for_status()
        _area_tree = r.json()
        _cache_set(AREAS_CACHE_KEY, _pack_json(_area_tree), AREAS_TTL_SECONDS, tags=["hh-areas"])
        try:
            with open(AREAS_CACHE, "w", encoding="utf-8") as f:
                json.dump(_area_tree, f, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Не удалось сохранить areas_cache локально: {e}")
        return _area_tree
    except Exception as e:
        print(f"❌ Ошибка загрузки дерева регионов: {e}")
        return []


def get_hh_dictionaries():
    global _hh_dictionaries
    if _hh_dictionaries is not None:
        return _hh_dictionaries

    cached_dicts = _cache_get(DICTS_CACHE_KEY)
    if cached_dicts is not None:
        _hh_dictionaries = cached_dicts
        return _hh_dictionaries

    try:
        response = requests.get(f"{HH_API}/dictionaries", timeout=20)
        response.raise_for_status()
        _hh_dictionaries = response.json()
        _cache_set(DICTS_CACHE_KEY, _hh_dictionaries, AREAS_TTL_SECONDS, tags=["hh-dictionaries"])
    except Exception as e:
        print(f"⚠️ Не удалось загрузить словари HH: {e}")
        _hh_dictionaries = {}
    return _hh_dictionaries


def get_employment_options():
    global _employment_options
    if _employment_options is not None:
        return _employment_options

    items = get_hh_dictionaries().get("employment", [])
    options = {item.get("id"): item.get("name") for item in items if item.get("id") and item.get("name")}
    if not options:
        options = {
            "full": "Полная занятость",
            "part": "Частичная занятость",
            "project": "Проектная работа",
            "volunteer": "Волонтерство",
            "probation": "Стажировка",
        }
    _employment_options = options
    return _employment_options


def get_work_format_options():
    global _work_format_options
    if _work_format_options is not None:
        return _work_format_options

    items = get_hh_dictionaries().get("work_format", [])
    options = {item.get("id"): item.get("name") for item in items if item.get("id") and item.get("name")}
    if not options:
        options = {
            "REMOTE": "Удалённо",
            "HYBRID": "Гибрид",
            "ON_SITE": "На месте работодателя",
            "FIELD_WORK": "Разъездной",
        }
    _work_format_options = options
    return _work_format_options

def _index_areas():
    global _area_by_id, _area_by_name
    if _area_by_id is not None and _area_by_name is not None:
        return _area_by_id, _area_by_name

    by_id = {}
    by_name = {}

    def walk(area):
        area_id = str(area.get("id", "")).strip()
        area_name = (area.get("name") or "").strip()
        if area_id:
            by_id[area_id] = area
        if area_name:
            by_name.setdefault(area_name.casefold(), []).append(area)
        for child in area.get("areas", []):
            walk(child)

    for root in get_area_tree():
        walk(root)

    _area_by_id = by_id
    _area_by_name = by_name
    return _area_by_id, _area_by_name

def find_area_id(name):
    if not name:
        return None

    _, by_name = _index_areas()
    normalized = name.strip().casefold()
    exact = by_name.get(normalized, [])
    if exact:
        return int(exact[0]["id"])

    partial_matches = []
    for area_name, areas in by_name.items():
        if normalized in area_name:
            partial_matches.extend(areas)

    unique_ids = []
    seen_ids = set()
    for area in partial_matches:
        area_id = str(area.get("id", ""))
        if area_id and area_id not in seen_ids:
            seen_ids.add(area_id)
            unique_ids.append(area)

    if len(unique_ids) == 1:
        return int(unique_ids[0]["id"])
    return None

def _collect_ids(area, ids):
    ids.add(str(area["id"]))
    for sub in area.get("areas", []):
        _collect_ids(sub, ids)

def get_area_children(area_id):
    area_id = str(area_id)
    if area_id in _area_children_cache:
        return _area_children_cache[area_id]

    by_id, _ = _index_areas()
    node = by_id.get(area_id)
    ids = set()
    if node:
        _collect_ids(node, ids)
    elif area_id:
        ids.add(area_id)

    _area_children_cache[area_id] = ids
    return ids


def expand_area_ids(area_ids):
    expanded = set()
    for area_id in area_ids or []:
        expanded.update(get_area_children(area_id))
    return expanded


# ═══════════════════════════════════════════════════════════
#  ПОИСК ВАКАНСИЙ
# ═══════════════════════════════════════════════════════════

def _vacancy_text_parts(vacancy):
    snippet = vacancy.get("snippet") or {}
    return {
        "title": (vacancy.get("name") or "").lower(),
        "description": f"{snippet.get('requirement') or ''} {snippet.get('responsibility') or ''}".lower(),
        "employer": ((vacancy.get("employer") or {}).get("name") or "").lower(),
    }


def _keyword_hit(parts, keywords, where):
    if not keywords:
        return False

    title_text = parts["title"]
    desc_text = parts["description"]

    for keyword in keywords:
        hit_title = where in ("title", "both") and keyword in title_text
        hit_desc = where in ("description", "both") and keyword in desc_text
        if hit_title or hit_desc:
            return True
    return False


def _vacancy_work_format_ids(vacancy):
    work_format = vacancy.get("work_format")
    ids = set()

    if isinstance(work_format, list):
        for item in work_format:
            work_format_id = (item or {}).get("id")
            if work_format_id:
                ids.add(str(work_format_id))
    elif isinstance(work_format, dict):
        work_format_id = work_format.get("id")
        if work_format_id:
            ids.add(str(work_format_id))

    if not ids:
        schedule_id = ((vacancy.get("schedule") or {}).get("id") or "").strip()
        if schedule_id == "remote":
            ids.add("REMOTE")

    return ids


def _vacancy_employment_id(vacancy):
    employment = vacancy.get("employment") or {}
    return str(employment.get("id") or "").strip()


def fetch_vacancies(template):
    template = _normalize_template(template)

    included_area_ids = [str(x) for x in template.get("included_area_ids", [])]
    excluded_area_ids = [str(x) for x in template.get("excluded_area_ids", [])]
    included_area_set = expand_area_ids(included_area_ids)
    excluded_area_set = expand_area_ids(excluded_area_ids)

    include_kw = [k.lower() for k in template.get("include_keywords", [])]
    include_in = template.get("include_in", "both")
    excl_kw = [k.lower() for k in template.get("exclude_keywords", [])]
    excl_in = template.get("exclude_in", "both")
    work_formats = set(template.get("work_formats", []))
    employment_types = set(template.get("employment_types", []))
    only_with_salary = bool(template.get("only_with_salary"))
    salary_min = max(0, int(template.get("salary_min", 0) or 0))
    excluded_employers = [name.lower() for name in template.get("excluded_employers", [])]
    sort_by = template.get("sort", "publication_time")
    queries = template.get("queries", DEFAULT_QUERIES)
    max_pages = int(template.get("max_pages", 5) or 5)
    period_days = int(template.get("period_days", 1) or 1)
    max_results = int(template.get("max_results", 50) or 50)
    search_fields = template.get("search_fields", ["name", "company_name", "description"])

    exp_list = template.get("experience", [ANY_EXPERIENCE])
    if ANY_EXPERIENCE in exp_list or not exp_list:
        exp_filters = [None]
    else:
        exp_filters = exp_list

    api_sort = sort_by if sort_by in API_SORT_OPTIONS else "publication_time"

    results = []
    seen_ids = set()
    errors = []
    requests_made = 0

    for query in queries:
        for exp in exp_filters:
            stale_pages = 0
            for page in range(max_pages):
                params = {
                    "text":            query,
                    "search_field":    search_fields,
                    "per_page":        50,
                    "page":            page,
                    "order_by":        api_sort,
                    "period":          period_days,
                    "enable_snippets": "true",
                }

                if exp:
                    params["experience"] = exp
                if included_area_ids:
                    params["area"] = included_area_ids

                try:
                    r = requests.get(f"{HH_API}/vacancies", params=params, timeout=20)
                    requests_made += 1
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:
                    exp_label = EXPERIENCE_OPTIONS.get(exp, "любой опыт") if exp else "любой опыт"
                    error_text = f"{query} / {exp_label}: {e}"
                    print(f"❌ Ошибка запроса hh.ru: {error_text}")
                    errors.append(error_text)
                    break

                items = data.get("items", [])
                if not items:
                    break

                fresh_ids_on_page = 0

                for v in items:
                    vid = str(v.get("id", ""))
                    if not vid or vid in seen_ids:
                        continue
                    seen_ids.add(vid)
                    fresh_ids_on_page += 1

                    area_id = str(v.get("area", {}).get("id", ""))
                    if included_area_set and area_id not in included_area_set:
                        continue
                    if excluded_area_set and area_id in excluded_area_set:
                        continue

                    parts = _vacancy_text_parts(v)

                    if include_kw and not _keyword_hit(parts, include_kw, include_in):
                        continue

                    if excl_kw:
                        if _keyword_hit(parts, excl_kw, excl_in):
                            continue

                    employer_name = parts["employer"]
                    if excluded_employers and any(name in employer_name for name in excluded_employers):
                        continue

                    if work_formats:
                        vacancy_work_formats = _vacancy_work_format_ids(v)
                        if not (vacancy_work_formats & work_formats):
                            continue

                    if employment_types:
                        if _vacancy_employment_id(v) not in employment_types:
                            continue

                    salary_value = _salary_key(v)
                    if only_with_salary and salary_value < 0:
                        continue
                    if salary_min and salary_value < salary_min:
                        continue

                    results.append(v)

                if fresh_ids_on_page == 0:
                    stale_pages += 1
                    if stale_pages >= 2:
                        break
                else:
                    stale_pages = 0

                total_pages = data.get("pages", 1)
                if page >= total_pages - 1:
                    break

                time.sleep(0.25)

    final = []
    seen_final = set()
    for v in results:
        vid = str(v.get("id", ""))
        if vid not in seen_final:
            seen_final.add(vid)
            final.append(v)

    sorted_final = _sort_vacancies(final, sort_by, queries)
    return {
        "vacancies": sorted_final[:max_results],
        "errors": _unique_list(errors),
        "requests_made": requests_made,
        "queries_count": len(queries),
    }


def _normalize_text(text):
    clean = re.sub(r"[^0-9a-zа-яё]+", " ", (text or "").lower(), flags=re.IGNORECASE)
    return " ".join(clean.split())


def _publication_key(vacancy):
    return (
        vacancy.get("published_at")
        or vacancy.get("created_at")
        or vacancy.get("publication_time")
        or ""
    )


def _salary_key(vacancy):
    salary = vacancy.get("salary") or {}
    values = [salary.get("to"), salary.get("from")]
    for value in values:
        if isinstance(value, (int, float)):
            return float(value)
    return -1.0


def _match_score(vacancy, queries):
    snippet = vacancy.get("snippet") or {}
    title = _normalize_text(vacancy.get("name", ""))
    employer = _normalize_text((vacancy.get("employer") or {}).get("name", ""))
    description = _normalize_text(
        f"{snippet.get('requirement') or ''} {snippet.get('responsibility') or ''} {employer}"
    )

    best = 0
    title_tokens = set(title.split())
    desc_tokens = set(description.split())

    for query in queries or []:
        normalized_query = _normalize_text(query)
        if not normalized_query:
            continue

        score = 0
        query_tokens = set(normalized_query.split())

        if normalized_query == title:
            score += 140
        elif normalized_query in title:
            score += 110
        elif normalized_query in description:
            score += 50

        if query_tokens:
            title_overlap = len(query_tokens & title_tokens) / len(query_tokens)
            desc_overlap = len(query_tokens & desc_tokens) / len(query_tokens)
            score += int(title_overlap * 80)
            score += int(desc_overlap * 25)

        best = max(best, score)

    return best


def _sort_vacancies(vacancies, sort_by, queries):
    if sort_by in ("relevance", "match_desc"):
        return sorted(
            vacancies,
            key=lambda v: (_match_score(v, queries), _publication_key(v)),
            reverse=True,
        )

    if sort_by == "name_asc":
        return sorted(
            vacancies,
            key=lambda v: (_normalize_text(v.get("name", "")), _publication_key(v)),
        )

    if sort_by == "salary_desc":
        return sorted(
            vacancies,
            key=lambda v: (_salary_key(v), _publication_key(v)),
            reverse=True,
        )

    if sort_by == "salary_asc":
        return sorted(
            vacancies,
            key=lambda v: (
                10**12 if _salary_key(v) < 0 else _salary_key(v),
                _normalize_text(v.get("name", "")),
            ),
        )

    return sorted(vacancies, key=_publication_key, reverse=True)

def format_vacancy(v):
    name     = _esc(v.get("name") or "—")
    employer = _esc((v.get("employer") or {}).get("name") or "—")
    area     = _esc((v.get("area") or {}).get("name") or "—")
    url      = v.get("alternate_url") or ""
    exp      = _esc((v.get("experience") or {}).get("name") or "—")
    schedule = _esc((v.get("schedule") or {}).get("name") or "")
    work_formats = ", ".join(
        _esc((item or {}).get("name") or "")
        for item in (v.get("work_format") or [])
        if (item or {}).get("name")
    )

    salary = v.get("salary")
    if salary:
        lo, hi, cur = salary.get("from"), salary.get("to"), salary.get("currency", "")
        if lo and hi:
            sal = f"{lo:,}–{hi:,} {cur}".replace(",", " ")
        elif lo:
            sal = f"от {lo:,} {cur}".replace(",", " ")
        elif hi:
            sal = f"до {hi:,} {cur}".replace(",", " ")
        else:
            sal = "не указана"
    else:
        sal = "не указана"

    snippet = v.get("snippet") or {}
    req = _esc((snippet.get("requirement") or "")[:200])
    req = req.replace("&lt;highlighttext&gt;", "<b>").replace("&lt;/highlighttext&gt;", "</b>")

    lines = [
        f"<b>{name}</b>",
        f"Компания: {employer}",
        f"Локация: {area}",
        f"Опыт: {exp}",
        f"Зарплата: {sal}",
    ]
    if work_formats:
        lines.append(f"Формат работы: {work_formats}")
    if schedule:
        lines.append(f"График: {schedule}")
    if req:
        lines.append(f"\n<i>{req}</i>")
    if url:
        lines.append(f"\n<a href='{url}'>Открыть вакансию на hh.ru</a>")

    return "\n".join(lines)


def _vacancy_salary_text(vacancy):
    salary = vacancy.get("salary") or {}
    lo, hi, cur = salary.get("from"), salary.get("to"), salary.get("currency", "")
    if lo and hi:
        return f"{lo:,}–{hi:,} {cur}".replace(",", " ")
    if lo:
        return f"от {lo:,} {cur}".replace(",", " ")
    if hi:
        return f"до {hi:,} {cur}".replace(",", " ")
    return "не указана"


def format_vacancy_brief(index, vacancy):
    name = _esc(vacancy.get("name") or "Без названия")
    employer = _esc((vacancy.get("employer") or {}).get("name") or "Компания не указана")
    area = _esc((vacancy.get("area") or {}).get("name") or "Локация не указана")
    exp = _esc((vacancy.get("experience") or {}).get("name") or "Не указан")
    salary = _esc(_vacancy_salary_text(vacancy))
    url = vacancy.get("alternate_url") or ""
    work_formats = ", ".join(
        _esc((item or {}).get("name") or "")
        for item in (vacancy.get("work_format") or [])
        if (item or {}).get("name")
    )

    lines = [
        f"<b>{index}. {name}</b>",
        f"{employer} · {area}",
        f"Опыт: {exp}",
        f"Зарплата: {salary}",
    ]
    if work_formats:
        lines.append(f"Формат: {work_formats}")
    if url:
        lines.append(f"<a href='{url}'>Открыть на hh.ru</a>")
    return "\n".join(lines)


def _store_result_session(data, tmpl, vacancies, persist, errors):
    session_id = str(uuid.uuid4())[:8]
    data.setdefault("result_sessions", {})[session_id] = {
        "template_id": tmpl["id"],
        "template_name": tmpl["name"],
        "created_at": time.time(),
        "page_size": tmpl.get("delivery_page_size", 5),
        "current_page": 0,
        "vacancies": vacancies,
        "mode": "run" if persist else "preview",
        "errors": list(errors or []),
    }
    _trim_result_sessions(data)
    return session_id


def _render_result_page(data, session_id, page):
    session = (data.get("result_sessions", {}) or {}).get(session_id)
    if not session:
        return None, None

    vacancies = session.get("vacancies", [])
    page_size = max(1, int(session.get("page_size", 5) or 5))
    page_count = _result_session_page_count(session)
    page = max(0, min(page, page_count - 1))
    session["current_page"] = page

    start = page * page_size
    end = start + page_size
    items = vacancies[start:end]
    mode_label = "Поиск" if session.get("mode") == "run" else "Предпросмотр"

    lines = [
        f"<b>{_esc(mode_label)}: {_esc(session.get('template_name', 'Поиск'))}</b>",
        f"Найдено: <b>{len(vacancies)}</b>",
        f"Страница: <b>{page + 1}/{page_count}</b>",
    ]

    if session.get("errors"):
        lines.append(f"Ошибки: <code>{_esc('; '.join(session['errors'][:2]))}</code>")

    if not items:
        lines.append("\nНечего показать на этой странице.")
    else:
        lines.append("")
        for index, vacancy in enumerate(items, start=start + 1):
            lines.append(format_vacancy_brief(index, vacancy))
            lines.append("")

    buttons = []
    nav_row = []
    if page > 0:
        nav_row.append({"text": "Назад", "callback_data": f"res_{session_id}_{page - 1}"})
    if page < page_count - 1:
        nav_row.append({"text": "Далее", "callback_data": f"res_{session_id}_{page + 1}"})
    if nav_row:
        buttons.append(nav_row)
    buttons.extend(_back_home_row("menu_current"))
    return "\n".join(lines).strip(), {"inline_keyboard": buttons}


# ═══════════════════════════════════════════════════════════
#  WIZARD — МАСТЕР СОЗДАНИЯ ШАБЛОНА
# ═══════════════════════════════════════════════════════════

def _format_template_summary(template, detailed=False):
    template = _normalize_template(template)
    exp_names = [EXPERIENCE_OPTIONS.get(code, code) for code in template.get("experience", [])]
    search_fields = [SEARCH_FIELD_OPTIONS.get(code, code) for code in template.get("search_fields", [])]
    include_names = template.get("included_area_names", [])
    exclude_names = template.get("excluded_area_names", [])
    include_kw = template.get("include_keywords", [])
    exclude_kw = template.get("exclude_keywords", [])
    work_formats = [get_work_format_options().get(code, code) for code in template.get("work_formats", [])]
    employment_types = [get_employment_options().get(code, code) for code in template.get("employment_types", [])]
    excluded_employers = template.get("excluded_employers", [])

    if not include_names and exclude_names == ["Россия"]:
        include_text = "Все страны, кроме России"
    elif not include_names:
        include_text = "Все страны и города"
    else:
        include_text = ", ".join(_esc(name) for name in include_names)
    exclude_text = ", ".join(_esc(name) for name in exclude_names) if exclude_names else "Без исключений"
    include_kw_preview = ", ".join(_esc(word) for word in include_kw[:6]) or "нет"
    exclude_kw_preview = ", ".join(_esc(word) for word in exclude_kw[:6]) or "нет"
    if len(include_kw) > 6:
        include_kw_preview += f" ... (+{len(include_kw) - 6})"
    if len(exclude_kw) > 6:
        exclude_kw_preview += f" ... (+{len(exclude_kw) - 6})"

    lines = [
        f"<b>{_esc(template.get('name', 'Новый сценарий'))}</b>",
        f"Запросов: <b>{len(template.get('queries', []))}</b>",
        f"Поля поиска: {_esc(', '.join(search_fields) or '—')}",
        f"Опыт: {_esc(', '.join(exp_names) or '—')}",
        f"Искать в: {include_text}",
        f"Исключить регионы: {exclude_text}",
        f"Включающие слова: <i>{include_kw_preview}</i>",
        f"Где искать включающие слова: {_esc({'title': 'только название', 'description': 'только описание', 'both': 'и название, и описание'}.get(template.get('include_in', 'both'), 'и название, и описание'))}",
        f"Исключающие слова: <i>{exclude_kw_preview}</i>",
        f"Где применять исключения: {_esc({'title': 'только название', 'description': 'только описание', 'both': 'и название, и описание'}.get(template.get('exclude_in', 'both'), 'и название, и описание'))}",
        f"Сортировка: {_esc(SORT_OPTIONS.get(template.get('sort', ''), '—'))}",
        f"Период: {_esc(PERIOD_OPTIONS.get(template.get('period_days', 1), 'За 1 день'))}",
        f"Страниц на запрос: {template.get('max_pages', 5)}",
        f"Лимит результатов: {template.get('max_results', 50)}",
        f"В одной странице выдачи: {template.get('delivery_page_size', 5)}",
        f"Интервал: {template.get('interval', 30)} мин",
    ]

    if detailed:
        lines.extend([
            f"Форматы работы: {_esc(', '.join(work_formats) or 'Любые')}",
            f"Тип занятости: {_esc(', '.join(employment_types) or 'Любой')}",
            f"Только с зарплатой: {'да' if template.get('only_with_salary') else 'нет'}",
            f"Минимальная зарплата: {template.get('salary_min', 0) or 'не задана'}",
            f"Исключённые работодатели: {_esc(', '.join(excluded_employers) or 'нет')}",
            f"Примеры запросов: <i>{_esc(', '.join(template.get('queries', [])[:6]))}</i>",
        ])

    return "\n".join(lines)


def _compact_preview(values, limit=2, empty_text="—"):
    items = [str(value).strip() for value in (values or []) if str(value).strip()]
    if not items:
        return empty_text
    shown = items[:limit]
    text = ", ".join(shown)
    if len(items) > limit:
        text += f" +{len(items) - limit}"
    return text


def _format_launch_message(template, preview=False):
    template = _normalize_template(template)
    work_formats = [get_work_format_options().get(code, code) for code in template.get("work_formats", [])]
    included_areas = template.get("included_area_names", [])
    excluded_areas = template.get("excluded_area_names", [])

    title = "Предпросмотр вакансий" if preview else "Проверяю вакансии"
    query_text = _compact_preview(template.get("queries", []), limit=2, empty_text="без уточнения")
    format_text = _compact_preview(work_formats, limit=2, empty_text="любой формат работы")

    lines = [
        f"<b>{title}</b>",
        f"Запрос: <b>{_esc(query_text)}</b>",
        f"Формат: <b>{_esc(format_text)}</b>",
    ]

    if included_areas:
        lines.append(f"География: <b>{_esc(_compact_preview(included_areas, limit=2))}</b>")
    else:
        lines.append("География: <b>все регионы</b>")

    if excluded_areas:
        lines.append(f"Исключения: <b>{_esc(_compact_preview(excluded_areas, limit=2))}</b>")

    return "\n".join(lines)


def wizard_start(chat_id, data, template_id=None):
    """Запускает мастер создания или редактирования шаблона."""
    if template_id:
        tmpl  = next((t for t in data["templates"] if t["id"] == template_id), None)
        draft = _normalize_template(tmpl) if tmpl else _new_draft()
    else:
        draft = _new_draft()

    data["user_states"][str(chat_id)] = {
        "step":  "queries",
        "draft": draft,
        "history": [],
    }
    save_data(data)

    send_msg(
        chat_id,
        "<b>Мастер настройки поиска</b>\n\n"
        "<b>Запросы</b>\n"
        "Введите названия вакансий через запятую.\n"
        "Или напишите <code>default</code> для полного набора аналитических должностей и синонимов.\n\n"
        "Пример: <code>data analyst, product analyst, business analyst</code>\n\n"
        "Дальше я пошагово спрошу опыт, географию, слова, формат работы, зарплату и другие фильтры.",
        reply_markup={"inline_keyboard": _back_home_row()}
    )

def _new_draft():
    return _normalize_template({
        "id":               str(uuid.uuid4())[:8],
        "name":             "Новый сценарий",
        "queries":          DEFAULT_QUERIES[:],
        "search_fields":    ["name", "company_name", "description"],
        "experience":       [ANY_EXPERIENCE],
        "included_area_ids": [],
        "included_area_names": [],
        "excluded_area_ids": [],
        "excluded_area_names": [],
        "exclude_keywords": DEFAULT_EXCLUDE_KEYWORDS[:],
        "include_keywords": [],
        "include_in":       "both",
        "exclude_in":       "both",
        "work_formats":     [],
        "employment_types": [],
        "period_days":      1,
        "only_with_salary": False,
        "salary_min":       0,
        "excluded_employers": [],
        "max_results":      50,
        "delivery_page_size": 5,
        "sort":             "publication_time",
        "interval":         30,
        "max_pages":        5,
    })


def _resolve_area_names(names):
    area_ids = []
    resolved_names = []
    not_found = []

    for name in names:
        aid = find_area_id(name)
        if aid:
            area_ids.append(str(aid))
            resolved_names.append(name)
        else:
            not_found.append(name)

    return _unique_list(area_ids), resolved_names, not_found

def wizard_handle_text(chat_id, text, data):
    """Обрабатывает ввод текста в контексте wizard-шага. Возвращает True если обработано."""
    state = data["user_states"].get(str(chat_id))
    if not state:
        return False

    step  = state["step"]
    draft = state["draft"]
    txt   = text.strip()

    if step == "queries":
        if txt.lower() == "default":
            draft["queries"] = DEFAULT_QUERIES[:]
        else:
            draft["queries"] = [q.strip() for q in txt.split(",") if q.strip()]
        if not draft["queries"]:
            send_msg(chat_id, "Введите хотя бы один запрос или напишите <code>default</code>.")
            return True
        _wizard_move_to(state, "search_fields")
        save_data(data)
        _send_search_fields_kb(chat_id, draft["search_fields"])
        return True

    if step == "include_areas":
        names    = [n.strip() for n in txt.split(",") if n.strip()]
        area_ids, resolved_names, not_found = _resolve_area_names(names)
        if names and not area_ids:
            send_msg(chat_id, "Не удалось распознать ни один регион. Введите страны или города ещё раз через запятую.")
            return True
        draft["included_area_ids"] = area_ids
        draft["included_area_names"] = resolved_names
        if not_found:
            send_msg(chat_id, f"Не найдены регионы: <b>{', '.join(not_found)}</b>\nПродолжаю с найденными.")
        _wizard_move_to(state, "exclude_areas")
        save_data(data)
        _send_exclude_area_prompt(chat_id)
        return True

    if step == "exclude_areas":
        lo = txt.lower()
        if lo in SKIP_WORDS:
            draft["excluded_area_ids"] = []
            draft["excluded_area_names"] = []
        else:
            names = [n.strip() for n in txt.split(",") if n.strip()]
            area_ids, resolved_names, not_found = _resolve_area_names(names)
            draft["excluded_area_ids"] = area_ids
            draft["excluded_area_names"] = resolved_names
            if not_found:
                send_msg(chat_id, f"Не найдены регионы: <b>{', '.join(not_found)}</b>\nПродолжаю с найденными.")
        _wizard_move_to(state, "include_kw")
        save_data(data)
        _send_include_kw_prompt(chat_id)
        return True

    if step == "include_kw":
        lo = txt.lower()
        if lo in SKIP_WORDS:
            draft["include_keywords"] = []
            _wizard_move_to(state, "exclude_kw")
            save_data(data)
            _send_exclude_kw_prompt(chat_id)
            return True

        draft["include_keywords"] = [k.strip().lower() for k in txt.split(",") if k.strip()]
        if not draft["include_keywords"]:
            send_msg(chat_id, "Введите слова через запятую или напишите <code>нет</code>.")
            return True
        _wizard_move_to(state, "include_in")
        save_data(data)
        _send_include_in_kb(chat_id)
        return True

    if step == "exclude_kw":
        lo = txt.lower()
        if lo == "default":
            draft["exclude_keywords"] = DEFAULT_EXCLUDE_KEYWORDS[:]
        elif lo in SKIP_WORDS:
            draft["exclude_keywords"] = []
            _wizard_move_to(state, "work_formats")
            save_data(data)
            _send_work_formats_kb(chat_id, draft.get("work_formats", []))
            return True

        draft["exclude_keywords"] = [k.strip().lower() for k in txt.split(",") if k.strip()]
        if not draft["exclude_keywords"]:
            send_msg(chat_id, "Введите слова через запятую, <code>default</code> или <code>нет</code>.")
            return True
        _wizard_move_to(state, "exclude_in")
        save_data(data)
        _send_exclude_in_kb(chat_id)
        return True

    if step == "work_formats":
        value_map = list(get_work_format_options().items())
        raw_items = [item.strip() for item in re.split(r"[,\s]+", txt) if item.strip()]
        if not raw_items:
            send_msg(chat_id, "Введите номера пунктов через запятую. Например: <code>1,2</code>.")
            return True
        if txt.lower() in SKIP_WORDS:
            draft["work_formats"] = []
            _wizard_move_to(state, "employment")
            save_data(data)
            _send_employment_kb(chat_id, draft.get("employment_types", []))
            return True

        selected_codes = []
        wrong_items = []
        for item in raw_items:
            if not item.isdigit():
                wrong_items.append(item)
                continue
            index = int(item) - 1
            if index < 0 or index >= len(value_map):
                wrong_items.append(item)
                continue
            selected_codes.append(value_map[index][0])

        if wrong_items:
            send_msg(chat_id, f"Не понял номера: <code>{', '.join(wrong_items)}</code>")
            return True

        draft["work_formats"] = _unique_list(selected_codes)
        _wizard_move_to(state, "employment")
        save_data(data)
        _send_employment_kb(chat_id, draft.get("employment_types", []))
        return True

    if step == "salary_min":
        value = re.sub(r"[^0-9]", "", txt)
        if not value:
            send_msg(chat_id, "Введите число, например <code>120000</code>, или вернитесь назад через /new.")
            return True
        draft["only_with_salary"] = True
        draft["salary_min"] = int(value)
        _wizard_move_to(state, "employers")
        save_data(data)
        _send_employers_prompt(chat_id)
        return True

    if step == "employers":
        lo = txt.lower()
        if lo in SKIP_WORDS:
            draft["excluded_employers"] = []
        else:
            draft["excluded_employers"] = [item.strip().lower() for item in txt.split(",") if item.strip()]
        _wizard_move_to(state, "sort")
        save_data(data)
        _send_sort_kb(chat_id)
        return True

    if step == "name":
        if txt.lower() not in ("ok", "ок"):
            draft["name"] = txt[:50]
        _wizard_move_to(state, "confirm")
        save_data(data)
        _send_confirm(chat_id, draft)
        return True

    return False


# ── Шаги wizard (inline keyboards) ─────────────────────────

def _send_search_fields_kb(chat_id, selected):
    buttons = []
    for code, label in SEARCH_FIELD_OPTIONS.items():
        mark = "[x] " if code in selected else "[ ] "
        buttons.append([{"text": mark + label, "callback_data": f"sf_{code}"}])
    buttons.append([{"text": "Далее", "callback_data": "sf_done"}])
    buttons.extend(_back_home_row("wiz_back"))
    send_msg(chat_id, "<b>Где искать совпадения</b>\nВыберите одно или несколько полей:", reply_markup={"inline_keyboard": buttons})

def _send_experience_kb(chat_id, selected):
    buttons = []
    for code, label in EXPERIENCE_OPTIONS.items():
        mark = "[x] " if code in selected else "[ ] "
        buttons.append([{"text": mark + label, "callback_data": f"exp_{code}"}])
    buttons.append([{"text": "Далее", "callback_data": "exp_done"}])
    buttons.extend(_back_home_row("wiz_back"))
    send_msg(chat_id, "<b>Опыт работы</b>\nВыберите один или несколько вариантов:",
             reply_markup={"inline_keyboard": buttons})

def _send_area_scope_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": "Искать везде", "callback_data": "scope_all"}],
        [{"text": "Искать только в выбранных странах/городах", "callback_data": "scope_selected"}],
        *_back_home_row("wiz_back"),
    ]}
    send_msg(chat_id, "<b>География поиска</b>\nСначала выберите общий режим:", reply_markup=kb)

def _send_include_area_prompt(chat_id):
    examples = ", ".join(POPULAR_AREA_NAMES[:12])
    send_msg(
        chat_id,
        "<b>Страны / города для включения</b>\n"
        "Введите через запятую.\n\n"
        f"Примеры: {examples}\n\n"
        "Пример: <code>Грузия, Тбилиси, Беларусь</code>",
        reply_markup={"inline_keyboard": _back_home_row("wiz_back")}
    )

def _send_exclude_area_prompt(chat_id):
    send_msg(
        chat_id,
        "<b>Страны / города для исключения</b>\n"
        "Введите через запятую или <code>нет</code>, если исключений не нужно.\n\n"
        "Примеры:\n"
        "<code>Москва</code>\n"
        "<code>Москва, Минск</code>\n"
        "<code>Россия</code>",
        reply_markup={"inline_keyboard": _back_home_row("wiz_back")}
    )

def _send_include_kw_prompt(chat_id):
    send_msg(
        chat_id,
        "<b>Слова, которые должны присутствовать</b>\n"
        "Введите через запятую или <code>нет</code>, если такой фильтр не нужен.\n\n"
        "Пример: <code>sql, python, product</code>",
        reply_markup={"inline_keyboard": _back_home_row("wiz_back")}
    )

def _send_include_in_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": "Искать только в названии", "callback_data": "ii_title"}],
        [{"text": "Искать только в описании", "callback_data": "ii_description"}],
        [{"text": "Искать и в названии, и в описании", "callback_data": "ii_both"}],
        *_back_home_row("wiz_back"),
    ]}
    send_msg(chat_id, "<b>Где должны встречаться включающие слова</b>", reply_markup=kb)

def _send_exclude_kw_prompt(chat_id):
    send_msg(
        chat_id,
        "<b>Ключевые слова для исключения</b>\n\n"
        "• <code>default</code> — стандартный список (гемблинг, казино, беттинг и т.д.)\n"
        "• <code>нет</code>     — не фильтровать\n"
        "• Или введите свои слова через запятую\n\n"
        f"В дефолтном списке: <b>{len(DEFAULT_EXCLUDE_KEYWORDS)}</b> слов",
        reply_markup={"inline_keyboard": _back_home_row("wiz_back")}
    )

def _send_exclude_in_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": "Только в названии", "callback_data": "ei_title"}],
        [{"text": "Только в описании", "callback_data": "ei_description"}],
        [{"text": "И в названии, и в описании", "callback_data": "ei_both"}],
        *_back_home_row("wiz_back"),
    ]}
    send_msg(chat_id, "<b>Где применять фильтр слов</b>", reply_markup=kb)

def _work_formats_keyboard(selected):
    buttons = [[{"text": "Сбросить выбор (любой формат)", "callback_data": "wf_any"}]]
    for code, label in get_work_format_options().items():
        mark = "[x] " if code in selected else "[ ] "
        buttons.append([{"text": mark + label.replace("\xa0", " "), "callback_data": f"wf_{code}"}])
    buttons.append([{"text": "Далее", "callback_data": "wf_done"}])
    buttons.extend(_back_home_row("wiz_back"))
    return buttons

def _send_work_formats_kb(chat_id, selected):
    numbered_lines = []
    for index, (_, label) in enumerate(get_work_format_options().items(), start=1):
        numbered_lines.append(f"{index}. {label.replace(chr(160), ' ')}")
    send_msg(
        chat_id,
        "<b>Формат работы</b>\n"
        "Выберите кнопками или отправьте номера через запятую.\n"
        "Можно несколько вариантов сразу.\n\n"
        + "\n".join(numbered_lines),
        reply_markup={"inline_keyboard": _work_formats_keyboard(selected)},
    )

def _employment_keyboard(selected):
    buttons = [[{"text": "Сбросить выбор (любая занятость)", "callback_data": "emp_any"}]]
    for code, label in get_employment_options().items():
        mark = "[x] " if code in selected else "[ ] "
        buttons.append([{"text": mark + label, "callback_data": f"emp_{code}"}])
    buttons.append([{"text": "Далее", "callback_data": "emp_done"}])
    buttons.extend(_back_home_row("wiz_back"))
    return buttons

def _send_employment_kb(chat_id, selected):
    send_msg(chat_id, "<b>Тип занятости</b>\nВыберите один или несколько вариантов. Если ничего не выбрано, подойдут любые.", reply_markup={"inline_keyboard": _employment_keyboard(selected)})

def _send_salary_mode_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": "Без фильтра по зарплате", "callback_data": "sal_any"}],
        [{"text": "Только вакансии с зарплатой", "callback_data": "sal_only"}],
        [{"text": "Указать минимальную зарплату", "callback_data": "sal_min"}],
        *_back_home_row("wiz_back"),
    ]}
    send_msg(chat_id, "<b>Фильтр по зарплате</b>", reply_markup=kb)

def _send_employers_prompt(chat_id):
    send_msg(
        chat_id,
        "<b>Работодатели для исключения</b>\n"
        "Введите компании через запятую или <code>нет</code>.\n\n"
        "Пример: <code>ANCOR, Lenkep recruitment</code>",
        reply_markup={"inline_keyboard": _back_home_row("wiz_back")}
    )

def _send_sort_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": label, "callback_data": f"sort_{code}"}]
        for code, label in SORT_OPTIONS.items()
    ]}
    kb["inline_keyboard"].extend(_back_home_row("wiz_back"))
    send_msg(chat_id, "<b>Сортировка</b>", reply_markup=kb)

def _send_period_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": label, "callback_data": f"period_{days}"}]
        for days, label in PERIOD_OPTIONS.items()
    ]}
    kb["inline_keyboard"].extend(_back_home_row("wiz_back"))
    send_msg(chat_id, "<b>Период поиска</b>\nЗа какой период брать вакансии с hh.ru:", reply_markup=kb)

def _send_pages_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": label, "callback_data": f"pages_{pages}"}]
        for pages, label in MAX_PAGES_OPTIONS.items()
    ]}
    kb["inline_keyboard"].extend(_back_home_row("wiz_back"))
    send_msg(chat_id, "<b>Глубина поиска</b>\nСколько страниц просматривать для каждого запроса:", reply_markup=kb)

def _send_max_results_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": label, "callback_data": f"limit_{limit}"}]
        for limit, label in MAX_RESULTS_OPTIONS.items()
    ]}
    kb["inline_keyboard"].extend(_back_home_row("wiz_back"))
    send_msg(chat_id, "<b>Лимит за один запуск</b>\nСколько вакансий максимум отправлять за одну проверку:", reply_markup=kb)


def _send_page_size_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": label, "callback_data": f"psize_{size}"}]
        for size, label in PAGE_SIZE_OPTIONS.items()
    ]}
    kb["inline_keyboard"].extend(_back_home_row("wiz_back"))
    send_msg(chat_id, "<b>Размер страницы выдачи</b>\nСколько вакансий показывать за один экран:", reply_markup=kb)

def _send_interval_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": label, "callback_data": f"int_{mins}"}]
        for mins, label in INTERVAL_OPTIONS.items()
    ]}
    kb["inline_keyboard"].extend(_back_home_row("wiz_back"))
    send_msg(chat_id, "<b>Интервал автопроверки</b>", reply_markup=kb)

def _send_confirm(chat_id, draft):
    text = _format_template_summary(draft, detailed=True)
    kb = {"inline_keyboard": [
        [
            {"text": "Сохранить", "callback_data": "confirm_save"},
            {"text": "Отмена",   "callback_data": "confirm_cancel"},
        ],
        *_back_home_row("wiz_back"),
    ]}
    send_msg(chat_id, text, reply_markup=kb)


# ═══════════════════════════════════════════════════════════
#  КОМАНДЫ БОТА
# ═══════════════════════════════════════════════════════════

def _menu_reply_markup():
    return {"inline_keyboard": [
        [{"text": "Создать сценарий", "callback_data": "tmpl_new"},
         {"text": "Сценарии", "callback_data": "menu_templates"}],
        [{"text": "Активный сценарий", "callback_data": "menu_current"},
         {"text": "Проверить вакансии", "callback_data": "run_now"}],
        [{"text": "Автопоиск", "callback_data": "menu_status"},
         {"text": "Помощь", "callback_data": "menu_help"}],
    ]}


def _current_search_keyboard(data):
    return {"inline_keyboard": [
        [{"text": "Проверить вакансии", "callback_data": "run_now"},
         {"text": "Предпросмотр", "callback_data": "preview_now"}],
        [{"text": "Редактировать", "callback_data": f"tmpl_edit_{data.get('active_template_id') or ''}"},
         {"text": "Автопоиск", "callback_data": "toggle"}],
        [{"text": "Очистить отправленные", "callback_data": "reset_sent"}],
        [{"text": "Сценарии", "callback_data": "menu_templates"},
         {"text": "Главное меню", "callback_data": "menu_home"}],
    ]}


def cmd_menu(chat_id, data):
    data["chat_id"] = chat_id
    save_data(data)
    send_msg(
        chat_id,
        "<b>Главное меню</b>\n"
        "Выберите действие:\n"
        "• создать новый сценарий\n"
        "• открыть сохранённые сценарии\n"
        "• посмотреть активный сценарий\n"
        "• проверить вакансии прямо сейчас",
        reply_markup=_menu_reply_markup(),
    )


def cmd_start(chat_id, data):
    data["chat_id"] = chat_id
    save_data(data)
    send_msg(chat_id,
        "<b>HH.ru Vacancy Bot</b>\n\n"
        "Отслеживаю вакансии на hh.ru и присылаю новые по вашим критериям.\n\n"
        "<b>Команды:</b>\n"
        "/menu      — главное меню\n"
        "/new       — создать новый сценарий\n"
        "/templates — открыть сохранённые сценарии\n"
        "/current   — показать активный сценарий\n"
        "/run       — проверить вакансии прямо сейчас\n"
        "/preview   — предпросмотр без сохранения в историю\n"
        "/reset_sent — очистить историю отправок активного сценария\n"
        "/toggle    — включить/выключить автопоиск\n"
        "/status    — статус и статистика\n"
        "/help      — подробная справка"
        ,
        reply_markup=_menu_reply_markup()
    )

def cmd_help(chat_id):
    send_msg(chat_id,
        "<b>Как пользоваться</b>\n\n"
        "1. <b>/new</b> — создайте сценарий через мастер\n"
        "2. <b>/templates</b> — выберите или отредактируйте сохранённый сценарий\n"
        "3. <b>/run</b> — немедленно проверю новые вакансии\n"
        "4. <b>/preview</b> — покажу результат без записи в историю\n"
        "5. <b>/toggle</b> — пауза или запуск автопоиска\n"
        "6. <b>/current</b> — полная сводка активного сценария\n"
        "7. <b>/reset_sent</b> — очистка истории отправок активного сценария\n\n"
        "<b>Доступные фильтры:</b>\n"
        "• География: страны и города на включение и исключение\n"
        "• Опыт: любые HH-варианты, можно несколько\n"
        "• Поля поиска: название, компания, описание\n"
        "• Включающие и исключающие слова\n"
        "• Формат работы и тип занятости\n"
        "• Только вакансии с зарплатой и минимальная зарплата\n"
        "• Исключение работодателей\n"
        "• Сортировка, глубина страниц, период, лимит результатов и размер страницы выдачи",
        reply_markup={"inline_keyboard": _back_home_row("menu_home")}
    )


def cmd_current(chat_id, data):
    data["chat_id"] = chat_id
    save_data(data)
    tmpl = _active_template(data)
    if not tmpl:
        send_msg(chat_id, "Активный сценарий ещё не выбран. Создайте его через /new.", reply_markup={"inline_keyboard": _back_home_row("menu_home")})
        return
    send_msg(chat_id, _format_template_summary(tmpl, detailed=True), reply_markup=_current_search_keyboard(data))


def cmd_reset_sent(chat_id, data):
    data["chat_id"] = chat_id
    tmpl = _active_template(data)
    if not tmpl:
        save_data(data)
        send_msg(chat_id, "Нет активного сценария. Очищать пока нечего.")
        return

    _set_template_sent_ids(data, tmpl["id"], [])
    save_data(data)
    send_msg(chat_id, f"История отправок для сценария <b>{_esc(tmpl['name'])}</b> очищена.", reply_markup=_current_search_keyboard(data))

def cmd_toggle(chat_id, data):
    data["chat_id"] = chat_id
    if not _active_template(data):
        save_data(data)
        send_msg(chat_id, "Нет активного сценария. Сначала создайте или выберите его.", reply_markup={"inline_keyboard": _back_home_row("menu_home")})
        return

    data["searching"] = not data.get("searching", False)
    save_data(data)
    if data["searching"]:
        send_msg(chat_id, "<b>Автопоиск включён</b>\nНовые вакансии будут приходить по расписанию.", reply_markup=_current_search_keyboard(data))
    else:
        send_msg(chat_id, "<b>Автопоиск на паузе</b>\n/run — ручной запуск в любой момент.", reply_markup=_current_search_keyboard(data))

def cmd_status(chat_id, data):
    data["chat_id"] = chat_id
    save_data(data)

    tmpl     = _active_template(data)
    icon     = "Вкл." if data.get("searching") else "Пауза"
    st_text  = "активен" if data.get("searching") else "на паузе"
    last_ts  = data.get("last_check", 0)
    last_str = datetime.fromtimestamp(last_ts).strftime("%d.%m %H:%M") if last_ts else "никогда"
    current_sent = len(_template_sent_ids(data, tmpl["id"])) if tmpl else 0
    total_sent = len(data.get("sent_ids", []))

    text = (
        f"{icon} <b>Статус: {st_text}</b>\n\n"
        f"Активный сценарий: <b>{_esc(tmpl['name']) if tmpl else 'не выбран'}</b>\n"
        f"Последняя проверка: {last_str}\n"
        f"Отправлено по активному сценарию: {current_sent}\n"
        f"Отправлено всего: {total_sent}\n"
    )

    if tmpl and data.get("searching"):
        interval  = tmpl.get("interval", 30) * 60
        remaining = max(0, int(last_ts + interval - time.time()))
        if remaining > 0:
            text += f"Следующая проверка через: {remaining // 60} мин {remaining % 60} сек\n"

    kb = {"inline_keyboard": [
        [{"text": "Пауза" if data.get("searching") else "Включить",
          "callback_data": "toggle"},
         {"text": "Проверить вакансии", "callback_data": "run_now"}],
        [{"text": "Активный сценарий", "callback_data": "menu_current"},
         {"text": "Сценарии", "callback_data": "menu_templates"}],
        [{"text": "Главное меню", "callback_data": "menu_home"}],
    ]}
    send_msg(chat_id, text, reply_markup=kb)

def cmd_templates(chat_id, data, page=0):
    data["chat_id"] = chat_id
    save_data(data)
    tmpls = data.get("templates", [])
    if not tmpls:
        send_msg(chat_id, "Сохранённых сценариев пока нет. Создайте первый через /new.", reply_markup={"inline_keyboard": _back_home_row("menu_home")})
        return

    per_page = 4
    total_pages = max(1, (len(tmpls) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    current_items = tmpls[start:start + per_page]

    text = f"<b>Сценарии поиска</b>\nСтраница <b>{page + 1}/{total_pages}</b>\n\n"
    buttons = []
    for index, t in enumerate(current_items, start=start + 1):
        mark = "Активный" if t["id"] == data.get("active_template_id") else "Сохранён"
        text += (
            f"<b>{index}. {_esc(t['name'])}</b>\n"
            f"Статус: {mark}\n"
            f"Запросов: {len(t.get('queries', []))} · Интервал: {t.get('interval', 30)} мин\n"
            f"Страниц: {t.get('max_pages', 5)} · Лимит: {t.get('max_results', 50)} · В выдаче: {t.get('delivery_page_size', 5)}\n\n"
        )
        buttons.append([
            {"text": f"{index}. Открыть", "callback_data": f"tmpl_select_{t['id']}"},
            {"text": f"{index}. Изм.", "callback_data": f"tmpl_edit_{t['id']}"},
            {"text": f"{index}. Удал.", "callback_data": f"tmpl_delete_{t['id']}"},
        ])
    nav_row = []
    if page > 0:
        nav_row.append({"text": "Назад", "callback_data": f"tmpl_page_{page - 1}"})
    if page < total_pages - 1:
        nav_row.append({"text": "Далее", "callback_data": f"tmpl_page_{page + 1}"})
    if nav_row:
        buttons.append(nav_row)
    buttons.append([{"text": "Создать сценарий", "callback_data": "tmpl_new"}])
    buttons.extend(_back_home_row("menu_home"))
    send_msg(chat_id, text, reply_markup={"inline_keyboard": buttons})

def cmd_run(chat_id, data):
    data["chat_id"] = chat_id
    save_data(data)
    tmpl = _active_template(data)
    if not tmpl:
        send_msg(chat_id, "Нет активного сценария. Создайте его через /new.", reply_markup={"inline_keyboard": _back_home_row("menu_home")})
        return
    send_msg(chat_id, _format_launch_message(tmpl, preview=False))
    _run_search(chat_id, data, tmpl, persist=True)


def cmd_preview(chat_id, data):
    data["chat_id"] = chat_id
    save_data(data)
    tmpl = _active_template(data)
    if not tmpl:
        send_msg(chat_id, "Нет активного сценария. Создайте его через /new.", reply_markup={"inline_keyboard": _back_home_row("menu_home")})
        return
    send_msg(chat_id, _format_launch_message(tmpl, preview=True))
    _run_search(chat_id, data, tmpl, persist=False)


# ═══════════════════════════════════════════════════════════
#  ЗАПУСК ПОИСКА И ОТПРАВКА
# ═══════════════════════════════════════════════════════════

def _active_template(data):
    aid = data.get("active_template_id")
    if not aid:
        return None
    return next((t for t in data.get("templates", []) if t["id"] == aid), None)

def _execute_search_result(data, tmpl, persist=True):
    result = fetch_vacancies(tmpl)
    fetched_vacancies = result.get("vacancies", [])
    fetch_errors = result.get("errors", [])
    sent_ids = _template_sent_ids(data, tmpl["id"])
    sent_set = set(sent_ids)

    if persist:
        visible_vacancies = []
        for vacancy in fetched_vacancies:
            vacancy_id = str(vacancy.get("id", ""))
            if vacancy_id in sent_set:
                continue
            visible_vacancies.append(vacancy)
            sent_set.add(vacancy_id)
            sent_ids.append(vacancy_id)
        data["last_check"] = time.time()
        _set_template_sent_ids(data, tmpl["id"], sent_ids)
        save_data(data)
    else:
        visible_vacancies = list(fetched_vacancies)

    return {
        "fetched_vacancies": fetched_vacancies,
        "visible_vacancies": visible_vacancies,
        "errors": fetch_errors,
    }


def _run_search(chat_id, data, tmpl, persist=True):
    result = _execute_search_result(data, tmpl, persist=persist)
    fetched_vacancies = result["fetched_vacancies"]
    visible_vacancies = result["visible_vacancies"]
    fetch_errors = result["errors"]

    if not visible_vacancies:
        reason_lines = []
        if fetched_vacancies and persist:
            reason_lines.append("По фильтрам вакансии есть, но они уже были отправлены раньше.")
        else:
            reason_lines.append("По текущим фильтрам ничего не найдено.")
        if fetch_errors:
            reason_lines.append(f"Ошибка запроса: <code>{_esc('; '.join(fetch_errors[:2]))}</code>")
        reason_lines.append("Проверьте запросы, опыт, географию, формат работы и слова для исключения.")
        send_msg(chat_id, "\n".join(reason_lines), reply_markup=_current_search_keyboard(data))
        return {
            "total_found": len(fetched_vacancies),
            "sent_now": 0,
            "new_count": 0,
            "persist": bool(persist),
            "errors": fetch_errors,
        }

    session_id = _store_result_session(data, tmpl, visible_vacancies, persist, fetch_errors)
    text, markup = _render_result_page(data, session_id, 0)
    save_data(data)

    header_lines = [
        f"<b>{'Поиск' if persist else 'Предпросмотр'} завершён</b>",
        f"Поиск: <b>{_esc(tmpl['name'])}</b>",
        f"Найдено к показу: <b>{len(visible_vacancies)}</b>",
        f"Всего найдено по фильтрам: <b>{len(fetched_vacancies)}</b>",
    ]
    if fetch_errors:
        header_lines.append(f"Ошибки: <code>{_esc('; '.join(fetch_errors[:2]))}</code>")
    send_msg(chat_id, "\n".join(header_lines), reply_markup=_current_search_keyboard(data))
    send_msg(chat_id, text, reply_markup=markup)

    return {
        "total_found": len(fetched_vacancies),
        "sent_now": len(visible_vacancies),
        "new_count": len(visible_vacancies),
        "persist": bool(persist),
        "errors": fetch_errors,
    }


def _build_runtime_status(data=None):
    data = load_data() if data is None else _normalize_data(data)
    tmpl = _active_template(data)
    return {
        "service": "hh-vacancy-bot",
        "platform": "vercel" if IS_VERCEL else "local",
        "searching": bool(data.get("searching", False)),
        "chat_configured": bool(data.get("chat_id")),
        "active_template_id": tmpl.get("id") if tmpl else None,
        "active_template_name": tmpl.get("name") if tmpl else None,
        "templates_count": len(data.get("templates", [])),
        "last_check": int(data.get("last_check", 0) or 0),
        "uses_runtime_cache": _runtime_cache_available(),
        "webhook_target": get_telegram_webhook_target() if get_public_base_url() else None,
    }


def run_manual_search_tick(persist=True):
    data = load_data()
    chat_id = data.get("chat_id")
    tmpl = _active_template(data)

    if not chat_id:
        return {"ok": False, "status": "skipped", "reason": "chat_not_configured"}
    if not tmpl:
        return {"ok": False, "status": "skipped", "reason": "no_active_template"}

    result = _run_search(chat_id, data, tmpl, persist=persist)
    return {
        "ok": True,
        "status": "done",
        "template_id": tmpl["id"],
        "template_name": tmpl["name"],
        **result,
    }


def _show_wizard_step(chat_id, state):
    step = state.get("step")
    draft = state.get("draft", {})

    if step == "queries":
        send_msg(
            chat_id,
            "<b>Мастер настройки поиска</b>\n\n"
            "<b>Запросы</b>\n"
            "Введите названия вакансий через запятую.\n"
            "Или напишите <code>default</code>.\n\n"
            "Пример: <code>data analyst, product analyst</code>",
            reply_markup={"inline_keyboard": _back_home_row()},
        )
        return
    if step == "search_fields":
        _send_search_fields_kb(chat_id, draft.get("search_fields", []))
        return
    if step == "experience":
        _send_experience_kb(chat_id, draft.get("experience", []))
        return
    if step == "area_scope":
        _send_area_scope_kb(chat_id)
        return
    if step == "include_areas":
        _send_include_area_prompt(chat_id)
        return
    if step == "exclude_areas":
        _send_exclude_area_prompt(chat_id)
        return
    if step == "include_kw":
        _send_include_kw_prompt(chat_id)
        return
    if step == "include_in":
        _send_include_in_kb(chat_id)
        return
    if step == "exclude_kw":
        _send_exclude_kw_prompt(chat_id)
        return
    if step == "exclude_in":
        _send_exclude_in_kb(chat_id)
        return
    if step == "work_formats":
        _send_work_formats_kb(chat_id, draft.get("work_formats", []))
        return
    if step == "employment":
        _send_employment_kb(chat_id, draft.get("employment_types", []))
        return
    if step == "salary_mode":
        _send_salary_mode_kb(chat_id)
        return
    if step == "salary_min":
        send_msg(
            chat_id,
            "<b>Минимальная зарплата</b>\nВведите число, например <code>120000</code>.",
            reply_markup={"inline_keyboard": _back_home_row("wiz_back")},
        )
        return
    if step == "employers":
        _send_employers_prompt(chat_id)
        return
    if step == "sort":
        _send_sort_kb(chat_id)
        return
    if step == "period":
        _send_period_kb(chat_id)
        return
    if step == "pages":
        _send_pages_kb(chat_id)
        return
    if step == "max_results":
        _send_max_results_kb(chat_id)
        return
    if step == "page_size":
        _send_page_size_kb(chat_id)
        return
    if step == "interval":
        _send_interval_kb(chat_id)
        return
    if step == "name":
        send_msg(
            chat_id,
            "<b>Название поиска</b>\n"
            f"Текущее название: <code>{_esc(draft.get('name', 'Новый сценарий'))}</code>\n\n"
            "Введите новое название или <code>ok</code>, чтобы оставить текущее.",
            reply_markup={"inline_keyboard": _back_home_row("wiz_back")},
        )
        return
    if step == "confirm":
        _send_confirm(chat_id, draft)


# ═══════════════════════════════════════════════════════════
#  ОБРАБОТКА CALLBACK QUERY (нажатие кнопок)
# ═══════════════════════════════════════════════════════════

def handle_callback(cb, data):
    chat_id = cb["message"]["chat"]["id"]
    msg_id  = cb["message"]["message_id"]
    cb_id   = cb["id"]
    cdata   = cb.get("data", "")
    state   = data["user_states"].get(str(chat_id), {})
    draft   = state.get("draft", {})

    answer_cb(cb_id)

    # ── Статус / тоггл ────────────────────────────────────
    if cdata == "menu_home":
        data = load_data()
        cmd_menu(chat_id, data)
        return

    if cdata == "menu_status":
        data = load_data()
        cmd_status(chat_id, data)
        return

    if cdata == "toggle":
        cmd_toggle(chat_id, data)
        return

    if cdata == "run_now":
        data = load_data()
        cmd_run(chat_id, data)
        return

    if cdata == "preview_now":
        data = load_data()
        cmd_preview(chat_id, data)
        return

    if cdata == "menu_templates":
        data = load_data()
        cmd_templates(chat_id, data)
        return

    if cdata == "menu_current":
        data = load_data()
        cmd_current(chat_id, data)
        return

    if cdata == "menu_help":
        cmd_help(chat_id)
        return

    if cdata == "reset_sent":
        data = load_data()
        cmd_reset_sent(chat_id, data)
        return

    if cdata == "wiz_back":
        history = state.get("history", [])
        if not history:
            data.get("user_states", {}).pop(str(chat_id), None)
            save_data(data)
            cmd_menu(chat_id, data)
            return
        state["step"] = history.pop()
        save_data(data)
        _show_wizard_step(chat_id, state)
        return

    if cdata.startswith("res_"):
        _, session_id, page_text = cdata.split("_", 2)
        session = (data.get("result_sessions", {}) or {}).get(session_id)
        if not session:
            send_msg(chat_id, "Эта выдача уже недоступна. Запустите поиск ещё раз.", reply_markup={"inline_keyboard": _back_home_row("menu_current")})
            return
        text, markup = _render_result_page(data, session_id, int(page_text))
        save_data(data)
        edit_msg(chat_id, msg_id, text, reply_markup=markup)
        return

    # ── Шаблоны ───────────────────────────────────────────
    if cdata == "tmpl_new":
        data = load_data()
        wizard_start(chat_id, data)
        return

    if cdata.startswith("tmpl_page_"):
        data = load_data()
        cmd_templates(chat_id, data, int(cdata[len("tmpl_page_"):]))
        return

    if cdata.startswith("tmpl_select_"):
        tmpl_id = cdata[len("tmpl_select_"):]
        data["active_template_id"] = tmpl_id
        data["searching"]          = True
        data.setdefault("sent_ids_by_template", {}).setdefault(str(tmpl_id), [])
        save_data(data)
        tmpl = next((t for t in data["templates"] if t["id"] == tmpl_id), None)
        send_msg(
            chat_id,
            f"Активный сценарий: <b>{_esc(tmpl['name'])}</b>\nАвтопоиск включён.",
            reply_markup=_current_search_keyboard(data),
        )
        return

    if cdata.startswith("tmpl_edit_"):
        tmpl_id = cdata[len("tmpl_edit_"):]
        data    = load_data()
        wizard_start(chat_id, data, template_id=tmpl_id)
        return

    if cdata.startswith("tmpl_delete_"):
        tmpl_id = cdata[len("tmpl_delete_"):]
        data["templates"] = [t for t in data["templates"] if t["id"] != tmpl_id]
        data.get("sent_ids_by_template", {}).pop(str(tmpl_id), None)
        if data.get("active_template_id") == tmpl_id:
            data["active_template_id"] = None
            data["searching"]          = False
        save_data(data)
        send_msg(chat_id, "Поиск удалён.")
        data = load_data()
        cmd_templates(chat_id, data)
        return

    # ── Wizard: Search fields (multi-select) ──────────────
    if cdata.startswith("sf_") and cdata != "sf_done":
        code = cdata[3:]
        selected = draft.get("search_fields", [])
        if code in selected:
            selected.remove(code)
        else:
            selected.append(code)
        draft["search_fields"] = _unique_list(selected)
        state["draft"] = draft
        save_data(data)
        buttons = []
        for field_code, label in SEARCH_FIELD_OPTIONS.items():
            mark = "[x] " if field_code in draft["search_fields"] else "[ ] "
            buttons.append([{"text": mark + label, "callback_data": f"sf_{field_code}"}])
        buttons.append([{"text": "Далее", "callback_data": "sf_done"}])
        buttons.extend(_back_home_row("wiz_back"))
        edit_reply_markup(chat_id, msg_id, {"inline_keyboard": buttons})
        return

    if cdata == "sf_done":
        if not draft.get("search_fields"):
            draft["search_fields"] = ["name"]
        _wizard_move_to(state, "experience")
        save_data(data)
        _send_experience_kb(chat_id, draft["experience"])
        return

    # ── Wizard: Experience (multi-select) ─────────────────
    if cdata.startswith("exp_") and cdata != "exp_done":
        code     = cdata[4:]
        selected = draft.get("experience", [])
        if code in selected:
            selected.remove(code)
        else:
            if code == ANY_EXPERIENCE:
                selected = [ANY_EXPERIENCE]
            else:
                selected = [item for item in selected if item != ANY_EXPERIENCE]
                selected.append(code)
        draft["experience"] = _unique_list(selected) or [ANY_EXPERIENCE]
        state["draft"] = draft
        save_data(data)
        # Обновить кнопки in-place
        buttons = []
        for c, label in EXPERIENCE_OPTIONS.items():
            mark = "[x] " if c in draft["experience"] else "[ ] "
            buttons.append([{"text": mark + label, "callback_data": f"exp_{c}"}])
        buttons.append([{"text": "Далее", "callback_data": "exp_done"}])
        buttons.extend(_back_home_row("wiz_back"))
        edit_reply_markup(chat_id, msg_id, {"inline_keyboard": buttons})
        return

    if cdata == "exp_done":
        if not draft.get("experience"):
            draft["experience"] = [ANY_EXPERIENCE]
        _wizard_move_to(state, "area_scope")
        save_data(data)
        _send_area_scope_kb(chat_id)
        return

    # ── Wizard: Area scope ────────────────────────────────
    if cdata in ("scope_all", "scope_selected"):
        if cdata == "scope_all":
            draft["included_area_ids"] = []
            draft["included_area_names"] = []
            _wizard_move_to(state, "exclude_areas")
            save_data(data)
            _send_exclude_area_prompt(chat_id)
        else:
            _wizard_move_to(state, "include_areas")
            save_data(data)
            _send_include_area_prompt(chat_id)
        return

    # ── Wizard: Include in ────────────────────────────────
    if cdata.startswith("ii_"):
        draft["include_in"] = cdata[3:]
        state["draft"] = draft
        _wizard_move_to(state, "exclude_kw")
        save_data(data)
        _send_exclude_kw_prompt(chat_id)
        return

    # ── Wizard: Exclude in ────────────────────────────────
    if cdata.startswith("ei_"):
        draft["exclude_in"] = cdata[3:]
        state["draft"]      = draft
        _wizard_move_to(state, "work_formats")
        save_data(data)
        _send_work_formats_kb(chat_id, draft.get("work_formats", []))
        return

    # ── Wizard: Work formats ──────────────────────────────
    if cdata == "wf_any":
        draft["work_formats"] = []
        state["draft"] = draft
        save_data(data)
        edit_reply_markup(chat_id, msg_id, {"inline_keyboard": _work_formats_keyboard(draft.get("work_formats", []))})
        return

    if cdata.startswith("wf_") and cdata != "wf_done":
        code = cdata[3:]
        selected = draft.get("work_formats", [])
        if code in selected:
            selected.remove(code)
        else:
            selected.append(code)
        draft["work_formats"] = _unique_list(selected)
        state["draft"] = draft
        save_data(data)
        edit_reply_markup(chat_id, msg_id, {"inline_keyboard": _work_formats_keyboard(draft.get("work_formats", []))})
        return

    if cdata == "wf_done":
        _wizard_move_to(state, "employment")
        save_data(data)
        _send_employment_kb(chat_id, draft.get("employment_types", []))
        return

    # ── Wizard: Employment ────────────────────────────────
    if cdata == "emp_any":
        draft["employment_types"] = []
        state["draft"] = draft
        save_data(data)
        edit_reply_markup(chat_id, msg_id, {"inline_keyboard": _employment_keyboard(draft.get("employment_types", []))})
        return

    if cdata.startswith("emp_") and cdata != "emp_done":
        code = cdata[4:]
        selected = draft.get("employment_types", [])
        if code in selected:
            selected.remove(code)
        else:
            selected.append(code)
        draft["employment_types"] = _unique_list(selected)
        state["draft"] = draft
        save_data(data)
        edit_reply_markup(chat_id, msg_id, {"inline_keyboard": _employment_keyboard(draft.get("employment_types", []))})
        return

    if cdata == "emp_done":
        _wizard_move_to(state, "salary_mode")
        save_data(data)
        _send_salary_mode_kb(chat_id)
        return

    # ── Wizard: Salary ────────────────────────────────────
    if cdata == "sal_any":
        draft["only_with_salary"] = False
        draft["salary_min"] = 0
        state["draft"] = draft
        _wizard_move_to(state, "employers")
        save_data(data)
        _send_employers_prompt(chat_id)
        return

    if cdata == "sal_only":
        draft["only_with_salary"] = True
        draft["salary_min"] = 0
        state["draft"] = draft
        _wizard_move_to(state, "employers")
        save_data(data)
        _send_employers_prompt(chat_id)
        return

    if cdata == "sal_min":
        _wizard_move_to(state, "salary_min")
        save_data(data)
        send_msg(
            chat_id,
            "<b>Минимальная зарплата</b>\nВведите число, например <code>120000</code>.",
            reply_markup={"inline_keyboard": _back_home_row("wiz_back")}
        )
        return

    # ── Wizard: Sort ──────────────────────────────────────
    if cdata.startswith("sort_"):
        draft["sort"] = cdata[5:]
        state["draft"] = draft
        _wizard_move_to(state, "period")
        save_data(data)
        _send_period_kb(chat_id)
        return

    # ── Wizard: Period ────────────────────────────────────
    if cdata.startswith("period_"):
        draft["period_days"] = int(cdata[7:])
        state["draft"] = draft
        _wizard_move_to(state, "pages")
        save_data(data)
        _send_pages_kb(chat_id)
        return

    # ── Wizard: Pages ─────────────────────────────────────
    if cdata.startswith("pages_"):
        draft["max_pages"] = int(cdata[6:])
        state["draft"] = draft
        _wizard_move_to(state, "max_results")
        save_data(data)
        _send_max_results_kb(chat_id)
        return

    # ── Wizard: Max results ───────────────────────────────
    if cdata.startswith("limit_"):
        draft["max_results"] = int(cdata[6:])
        state["draft"] = draft
        _wizard_move_to(state, "page_size")
        save_data(data)
        _send_page_size_kb(chat_id)
        return

    if cdata.startswith("psize_"):
        draft["delivery_page_size"] = int(cdata[6:])
        state["draft"] = draft
        _wizard_move_to(state, "interval")
        save_data(data)
        _send_interval_kb(chat_id)
        return

    # ── Wizard: Interval ──────────────────────────────────
    if cdata.startswith("int_"):
        draft["interval"] = int(cdata[4:])
        state["draft"]    = draft
        _wizard_move_to(state, "name")
        save_data(data)
        send_msg(chat_id,
            "<b>Название поиска</b>\n"
            f"Текущее название: <code>{_esc(draft.get('name', 'Новый сценарий'))}</code>\n\n"
            "Введите новое название или <code>ok</code> чтобы оставить текущее.",
            reply_markup={"inline_keyboard": _back_home_row("wiz_back")}
        )
        return

    # ── Wizard: Confirm / Cancel ──────────────────────────
    if cdata == "confirm_save":
        tmpl     = state.get("draft", {})
        existing = [t for t in data["templates"] if t["id"] != tmpl["id"]]
        existing.append(tmpl)
        data["templates"]          = existing
        data["active_template_id"] = tmpl["id"]
        data["searching"]          = True
        data.setdefault("sent_ids_by_template", {}).setdefault(str(tmpl["id"]), [])
        if str(chat_id) in data["user_states"]:
            del data["user_states"][str(chat_id)]
        save_data(data)
        send_msg(chat_id,
            f"<b>Поиск «{_esc(tmpl['name'])}» сохранён.</b>\n"
            "Автопоиск включён.\n"
            "/run — запустить поиск прямо сейчас.",
            reply_markup=_current_search_keyboard(data)
        )
        return

    if cdata == "confirm_cancel":
        if str(chat_id) in data["user_states"]:
            del data["user_states"][str(chat_id)]
        save_data(data)
        send_msg(chat_id, "Создание поиска отменено.", reply_markup={"inline_keyboard": _back_home_row("menu_home")})
        return


# ═══════════════════════════════════════════════════════════
#  ДЕФОЛТНЫЙ ШАБЛОН (из требований пользователя)
# ═══════════════════════════════════════════════════════════

def _create_default_template():
    return _normalize_template({
        "id":                 "default01",
        "name":               "Аналитик — все страны кроме России",
        "queries":            DEFAULT_QUERIES[:],
        "search_fields":      ["name", "company_name", "description"],
        "experience":         ["noExperience", "between1And3"],
        "included_area_ids":  [],
        "included_area_names": [],
        "excluded_area_ids":  [str(RUSSIA_AREA_ID)],
        "excluded_area_names": ["Россия"],
        "include_keywords":   [],
        "include_in":         "both",
        "exclude_keywords":   DEFAULT_EXCLUDE_KEYWORDS[:],
        "exclude_in":         "both",
        "work_formats":       [],
        "employment_types":   [],
        "period_days":        3,
        "only_with_salary":   False,
        "salary_min":         0,
        "excluded_employers": [],
        "max_results":        50,
        "sort":               "match_desc",
        "interval":           30,
        "max_pages":          5,
    })


# ═══════════════════════════════════════════════════════════
#  ГЛАВНЫЙ ЦИКЛ
# ═══════════════════════════════════════════════════════════

def bootstrap_bot():
    print("🤖 HH.ru Vacancy Bot запускается...")
    data = load_data()

    if not data.get("templates"):
        tmpl = _create_default_template()
        data["templates"] = [tmpl]
        data["active_template_id"] = tmpl["id"]
        save_data(data)
        print("✅ Создан дефолтный шаблон поиска")

    print("📡 Загружаю дерево регионов HH...")
    _index_areas()
    get_hh_dictionaries()


def process_update(upd):
    data = load_data()

    if "callback_query" in upd:
        try:
            handle_callback(upd["callback_query"], data)
        except Exception as e:
            print(f"❌ Ошибка callback: {e}")
        return

    msg = upd.get("message", {})
    if not msg:
        return

    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    if not text:
        return

    if data.get("chat_id") != chat_id:
        data["chat_id"] = chat_id
        save_data(data)

    state = data["user_states"].get(str(chat_id))
    if state and not text.startswith("/"):
        if state["step"] == "name" and text.lower() in ("ok", "ок"):
            text = state["draft"].get("name", "Новый сценарий")
        try:
            wizard_handle_text(chat_id, text, data)
        except Exception as e:
            print(f"❌ Ошибка wizard: {e}")
        return

    cmd = text.split()[0].split("@")[0].lower()
    try:
        if cmd == "/start":
            cmd_start(chat_id, data)
        elif cmd == "/menu":
            cmd_menu(chat_id, data)
        elif cmd == "/help":
            cmd_help(chat_id)
        elif cmd == "/new":
            wizard_start(chat_id, data)
        elif cmd == "/templates":
            cmd_templates(chat_id, data)
        elif cmd == "/current":
            cmd_current(chat_id, data)
        elif cmd == "/run":
            cmd_run(chat_id, data)
        elif cmd == "/preview":
            cmd_preview(chat_id, data)
        elif cmd == "/reset_sent":
            cmd_reset_sent(chat_id, data)
        elif cmd == "/toggle":
            cmd_toggle(chat_id, data)
        elif cmd == "/status":
            cmd_status(chat_id, data)
        else:
            send_msg(chat_id, "Неизвестная команда. Откройте /menu и выберите нужный пункт.", reply_markup=_menu_reply_markup())
    except Exception as e:
        print(f"❌ Ошибка команды {cmd}: {e}")


def run_scheduled_search_tick(force=False):
    data = load_data()
    chat_id = data.get("chat_id")

    if not (data.get("searching") and data.get("active_template_id") and chat_id):
        return {"ok": False, "status": "skipped", "reason": "inactive_or_chat_missing"}

    tmpl = _active_template(data)
    if not tmpl:
        return {"ok": False, "status": "skipped", "reason": "no_active_template"}

    interval = tmpl.get("interval", 30) * 60
    last_chk = data.get("last_check", 0)
    if not force and time.time() - last_chk < interval:
        remaining = max(0, int(last_chk + interval - time.time()))
        return {
            "ok": True,
            "status": "skipped",
            "reason": "interval_not_reached",
            "remaining_seconds": remaining,
            "template_id": tmpl["id"],
            "template_name": tmpl["name"],
        }

    print(f"🔍 Плановый поиск: {tmpl['name']}")
    try:
        result = _run_search(chat_id, data, tmpl)
        return {
            "ok": True,
            "status": "done",
            "template_id": tmpl["id"],
            "template_name": tmpl["name"],
            **result,
        }
    except Exception as e:
        print(f"❌ Ошибка планового поиска: {e}")
        data["last_check"] = time.time()
        save_data(data)
        return {"ok": False, "status": "error", "reason": str(e)}


def _cron_request_authorized(auth_header="", query_secret=""):
    if not CRON_SECRET:
        return True
    if auth_header == f"Bearer {CRON_SECRET}":
        return True
    if query_secret and query_secret == CRON_SECRET:
        return True
    return False


def _web_request_authorized(request):
    if not WEB_ADMIN_TOKEN:
        return True
    header_token = (request.headers.get("x-admin-token") or "").strip()
    auth_header = (request.headers.get("authorization") or "").strip()
    query_token = (request.query_params.get("token") or "").strip()
    if header_token == WEB_ADMIN_TOKEN:
        return True
    if auth_header == f"Bearer {WEB_ADMIN_TOKEN}":
        return True
    if query_token == WEB_ADMIN_TOKEN:
        return True
    return False


def _web_search_response(data, tmpl, persist):
    result = _execute_search_result(data, tmpl, persist=persist)
    fetched_vacancies = result["fetched_vacancies"]
    visible_vacancies = result["visible_vacancies"]
    fetch_errors = result["errors"]

    if not visible_vacancies:
        if fetched_vacancies and persist:
            reason = "По фильтрам вакансии есть, но они уже были отправлены раньше."
        else:
            reason = "По текущим фильтрам ничего не найдено."
    else:
        reason = ""

    return {
        "template_id": tmpl["id"],
        "template_name": tmpl["name"],
        "persist": bool(persist),
        "total_found": len(fetched_vacancies),
        "shown_count": len(visible_vacancies),
        "page_size": int(tmpl.get("delivery_page_size", 5) or 5),
        "reason": reason,
        "errors": list(fetch_errors or []),
        "vacancies": [_vacancy_to_web_item(vacancy) for vacancy in visible_vacancies],
    }


def _web_ui_html():
    token_required = "true" if WEB_ADMIN_TOKEN else "false"
    return '''<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HH Vacancy Bot</title>
  <style>
    :root {
      --bg: #f5f7fb;
      --panel: #ffffff;
      --panel-soft: #f8fafc;
      --line: #e0e6ef;
      --line-strong: #cfd8e6;
      --text: #172033;
      --muted: #5f6f86;
      --accent: #356dff;
      --accent-2: #1f4ecf;
      --accent-soft: #eef3ff;
      --danger-soft: #fff0ec;
      --danger: #bc4f2f;
      --success-soft: #eaf8ef;
      --success: #217346;
      --shadow: 0 18px 44px rgba(27, 43, 80, 0.08);
      --radius: 20px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(53, 109, 255, 0.12), transparent 24%),
        radial-gradient(circle at top right, rgba(56, 189, 248, 0.10), transparent 22%),
        linear-gradient(180deg, #f8fbff 0%, #f4f7fb 100%);
      color: var(--text);
      font: 15px/1.5 "Segoe UI", "Helvetica Neue", sans-serif;
    }
    .page {
      max-width: 1500px;
      margin: 0 auto;
      padding: 24px 18px 44px;
    }
    .panel, .topbar, .stat-card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }
    .topbar {
      padding: 24px 26px;
      margin-bottom: 18px;
      display: grid;
      gap: 14px;
    }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      width: fit-content;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent-2);
      font-size: 12px;
      font-weight: 700;
      padding: 6px 10px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .topbar h1 {
      margin: 0;
      font-size: 34px;
      line-height: 1.08;
      letter-spacing: -0.03em;
    }
    .topbar p {
      margin: 0;
      max-width: 920px;
      color: var(--muted);
    }
    .status-strip {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      margin-bottom: 14px;
    }
    .stat-card {
      padding: 16px 18px;
      min-height: 108px;
    }
    .stat-card strong {
      display: block;
      margin-bottom: 10px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }
    .stat-value {
      font-size: 18px;
      font-weight: 700;
      line-height: 1.3;
      word-break: break-word;
    }
    .quick-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 18px;
    }
    .token-box {
      display: none;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      padding-top: 10px;
      border-top: 1px dashed var(--line-strong);
    }
    .token-box.visible {
      display: flex;
    }
    .layout {
      display: grid;
      gap: 18px;
      grid-template-columns: 340px minmax(0, 1fr);
      align-items: start;
    }
    .panel {
      padding: 20px;
    }
    .sidebar {
      position: sticky;
      top: 18px;
    }
    .sidebar-head,
    .section-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }
    .section-head h2,
    .sidebar-head h2,
    .panel h2 {
      margin: 0;
      font-size: 20px;
      letter-spacing: -0.02em;
    }
    .section-head p,
    .sidebar-head p {
      margin: 0;
      color: var(--muted);
      font-size: 14px;
    }
    .panel h3 {
      margin: 0 0 12px;
      font-size: 13px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .stack {
      display: grid;
      gap: 18px;
    }
    .grid-2 {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .grid-4 {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }
    label.field {
      display: grid;
      gap: 7px;
      font-weight: 600;
      color: var(--text);
    }
    .field small {
      color: var(--muted);
      font-weight: 400;
    }
    input[type="text"],
    input[type="number"],
    textarea,
    select {
      width: 100%;
      border: 1px solid var(--line-strong);
      border-radius: 14px;
      background: #fff;
      padding: 11px 12px;
      color: var(--text);
      font: inherit;
    }
    textarea {
      min-height: 96px;
      resize: vertical;
    }
    select[multiple] {
      min-height: 128px;
    }
    .check-grid {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }
    .check-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 9px 13px;
      border: 1px solid var(--line-strong);
      border-radius: 999px;
      background: #fff;
      color: var(--text);
      font-weight: 500;
    }
    .field-row {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }
    button {
      border: 0;
      border-radius: 14px;
      background: #ecf1f7;
      color: var(--text);
      padding: 11px 15px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      transition: transform 0.12s ease, background 0.12s ease, opacity 0.12s ease;
    }
    button:hover { transform: translateY(-1px); }
    button.primary { background: var(--accent); color: #fff; }
    button.secondary { background: var(--accent-soft); color: var(--accent-2); }
    button.ghost { background: transparent; border: 1px solid var(--line-strong); }
    button.danger { background: var(--danger-soft); color: var(--danger); }
    button.success { background: var(--success-soft); color: var(--success); }
    button:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
    .template-list {
      display: grid;
      gap: 10px;
    }
    .template-card {
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--panel-soft);
      padding: 15px;
      display: grid;
      gap: 10px;
    }
    .template-card.active {
      border-color: var(--accent);
      background: #fff;
      box-shadow: inset 0 0 0 1px rgba(53, 109, 255, 0.18);
    }
    .template-card h4 {
      margin: 0;
      font-size: 16px;
    }
    .template-meta {
      color: var(--muted);
      font-size: 13px;
      white-space: pre-line;
      word-break: break-word;
    }
    .message {
      display: none;
      padding: 12px 14px;
      border-radius: 14px;
      font-weight: 600;
      white-space: pre-line;
      word-break: break-word;
    }
    .message.info { display: block; background: #e6effc; color: #214d8e; }
    .message.success { display: block; background: #dbf0dc; color: #1c5d22; }
    .message.error { display: block; background: #f8d8d3; color: #7a1f16; }
    .hint {
      color: var(--muted);
      font-size: 13px;
    }
    .results-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }
    .results-list {
      display: grid;
      gap: 12px;
      margin-top: 14px;
    }
    .result-card {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
      background: #fff;
      display: grid;
      gap: 7px;
    }
    .result-card h4 {
      margin: 0;
      font-size: 17px;
    }
    .result-meta {
      color: var(--muted);
      font-size: 14px;
    }
    .filters-grid {
      display: grid;
      gap: 18px;
    }
    .pager {
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
      margin-top: 16px;
    }
    .summary-box {
      background: var(--panel-soft);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 15px;
      font-size: 14px;
      white-space: pre-line;
      word-break: break-word;
    }
    .empty-sidebar {
      color: var(--muted);
      font-size: 14px;
      padding: 10px 2px 0;
    }
    @media (max-width: 1180px) {
      .status-strip {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .layout { grid-template-columns: 1fr; }
      .sidebar { position: static; }
    }
    @media (max-width: 780px) {
      .grid-2, .grid-4, .status-strip { grid-template-columns: 1fr; }
      .page { padding: 16px 12px 28px; }
      .topbar { padding: 18px; }
      .topbar h1 { font-size: 28px; }
      .panel { padding: 16px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="topbar">
      <span class="eyebrow">HH.ru</span>
      <div>
        <h1>Поиск вакансий</h1>
        <p>
          Управляйте сохранёнными сценариями поиска без Telegram: настраивайте фильтры,
          включайте автопроверку, делайте ручную проверку и просматривайте найденные вакансии в одном месте.
        </p>
      </div>
      <div id="tokenBox" class="token-box">
        <input id="authToken" type="text" placeholder="Токен доступа для панели">
        <button id="saveTokenBtn" class="primary" type="button">Сохранить токен</button>
        <span class="hint">Нужен только если на сервере задан HH_WEB_ADMIN_TOKEN.</span>
      </div>
    </section>

    <div id="messageBox" class="message"></div>

    <section class="status-strip">
      <article class="stat-card">
        <strong>Автопоиск</strong>
        <div id="statusSearch" class="stat-value">Загрузка...</div>
      </article>
      <article class="stat-card">
        <strong>Активный сценарий</strong>
        <div id="statusTemplate" class="stat-value">Загрузка...</div>
      </article>
      <article class="stat-card">
        <strong>Telegram</strong>
        <div id="statusChat" class="stat-value">Загрузка...</div>
      </article>
      <article class="stat-card">
        <strong>Последняя проверка</strong>
        <div id="statusLastCheck" class="stat-value">Загрузка...</div>
      </article>
    </section>

    <section class="quick-actions">
      <button id="refreshBtn" class="ghost" type="button">Обновить данные</button>
      <button id="toggleBtn" class="secondary" type="button">Пауза автопоиска</button>
      <button id="runBtn" class="primary" type="button">Проверить вакансии</button>
      <button id="previewBtn" class="ghost" type="button">Предпросмотр выдачи</button>
    </section>

    <section class="layout">
      <aside class="panel sidebar">
        <div class="sidebar-head">
          <div>
            <h2>Сценарии поиска</h2>
            <p>Выберите существующий или создайте новый.</p>
          </div>
          <button id="newSearchBtn" class="primary" type="button">Создать сценарий</button>
        </div>
        <div id="templateList" class="template-list"></div>
      </aside>

      <div class="stack">
        <section class="panel">
          <div class="section-head">
            <div>
              <h2>Редактор сценария</h2>
              <p>Настройте, какие вакансии искать, где искать и как показывать результаты.</p>
            </div>
          </div>
          <div class="filters-grid">
            <div>
              <h3>Что ищем</h3>
              <div class="grid-2">
                <label class="field">
                  Название сценария
                  <input id="name" type="text" maxlength="50" placeholder="Например: Product / Data Analyst">
                </label>
                <label class="field">
                  Где искать совпадения
                  <select id="searchFields" multiple></select>
                  <small>Можно выбрать название, компанию и описание одновременно.</small>
                </label>
              </div>
              <label class="field" style="margin-top: 14px;">
                Запросы и синонимы
                <textarea id="queries" placeholder="По одному на строке или через запятую"></textarea>
              </label>
              <div class="field" style="margin-top: 14px;">
                Опыт работы
                <div id="experienceGroup" class="check-grid"></div>
              </div>
            </div>

            <div>
              <h3>Где ищем</h3>
              <div class="grid-2">
                <label class="field">
                  Включить регионы
                  <textarea id="includedAreas" placeholder="Например: Грузия, Казахстан, Тбилиси"></textarea>
                  <small>Если оставить пустым, поиск идёт по всем регионам.</small>
                </label>
                <label class="field">
                  Исключить регионы
                  <textarea id="excludedAreas" placeholder="Например: Россия, Москва"></textarea>
                  <small>Если исключаете страну, её города тоже исключаются автоматически.</small>
                </label>
              </div>
              <div class="summary-box" id="areaHint"></div>
            </div>

            <div>
              <h3>Фильтры</h3>
              <div class="grid-2">
                <label class="field">
                  Обязательные слова
                  <textarea id="includeKeywords" placeholder="Например: sql, python, retention"></textarea>
                </label>
                <label class="field">
                  Исключающие слова
                  <textarea id="excludeKeywords" placeholder="Например: casino, betting, sportsbook"></textarea>
                </label>
              </div>
              <div class="grid-2" style="margin-top: 14px;">
                <label class="field">
                  Где искать обязательные слова
                  <select id="includeIn">
                    <option value="both">И в названии, и в описании</option>
                    <option value="title">Только в названии</option>
                    <option value="description">Только в описании</option>
                  </select>
                </label>
                <label class="field">
                  Где применять исключения
                  <select id="excludeIn">
                    <option value="both">И в названии, и в описании</option>
                    <option value="title">Только в названии</option>
                    <option value="description">Только в описании</option>
                  </select>
                </label>
              </div>
              <label class="field" style="margin-top: 14px;">
                Исключить работодателей
                <textarea id="excludedEmployers" placeholder="Например: lenkep recruitment"></textarea>
              </label>
            </div>

            <div>
              <h3>Формат и деньги</h3>
              <div class="field">
                Формат работы
                <div id="workFormatsGroup" class="check-grid"></div>
              </div>
              <div class="field" style="margin-top: 14px;">
                Тип занятости
                <div id="employmentGroup" class="check-grid"></div>
              </div>
              <div class="grid-2" style="margin-top: 14px;">
                <label class="field">
                  Минимальная зарплата
                  <input id="salaryMin" type="number" min="0" step="1000" placeholder="0">
                </label>
                <label class="field">
                  Отбор по зарплате
                  <span class="check-pill">
                    <input id="onlyWithSalary" type="checkbox">
                    Показывать только вакансии с указанной зарплатой
                  </span>
                </label>
              </div>
            </div>

            <div>
              <h3>Как показывать результаты</h3>
              <div class="grid-4">
                <label class="field">
                  Сортировка
                  <select id="sort"></select>
                </label>
                <label class="field">
                  Период поиска
                  <select id="periodDays"></select>
                </label>
                <label class="field">
                  Страниц на запрос
                  <input id="maxPages" type="number" min="1" max="20">
                </label>
                <label class="field">
                  Лимит результатов
                  <input id="maxResults" type="number" min="1" max="500">
                </label>
                <label class="field">
                  На одной странице
                  <input id="deliveryPageSize" type="number" min="1" max="50">
                </label>
                <label class="field">
                  Интервал автопроверки, минут
                  <input id="interval" type="number" min="5" max="1440">
                </label>
              </div>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="section-head">
            <div>
              <h2>Сохранение и управление</h2>
              <p>Сохраняйте изменения, делайте сценарий активным и очищайте историю отправок.</p>
            </div>
          </div>
          <div class="actions">
            <button id="saveBtn" class="primary" type="button">Сохранить изменения</button>
            <button id="saveActivateBtn" class="secondary" type="button">Сохранить и включить</button>
            <button id="activateBtn" class="ghost" type="button">Сделать активным</button>
            <button id="resetSentBtn" class="ghost" type="button">Очистить отправленные</button>
            <button id="deleteBtn" class="danger" type="button">Удалить сценарий</button>
          </div>
          <div id="currentSummary" class="summary-box" style="margin-top: 14px;"></div>
        </section>

        <section class="panel">
          <div class="results-head">
            <div>
              <h2 style="margin-bottom: 6px;">Найденные вакансии</h2>
              <div id="resultsMeta" class="hint">Сначала запустите проверку или предпросмотр.</div>
            </div>
            <div class="actions">
              <button id="resultsPrev" class="ghost" type="button">Назад</button>
              <button id="resultsNext" class="ghost" type="button">Далее</button>
            </div>
          </div>
          <div id="resultsList" class="results-list"></div>
          <div class="pager">
            <span id="resultsPage" class="hint"></span>
          </div>
        </section>
      </div>
    </section>
  </div>

  <script>
    const TOKEN_REQUIRED = __TOKEN_REQUIRED__;
    const state = {
      data: null,
      selectedTemplateId: '',
      result: null,
      resultPage: 0,
      authToken: localStorage.getItem('hh_web_admin_token') || '',
    };

    const els = {};

    function qs(id) {
      return document.getElementById(id);
    }

    function splitValues(value) {
      return String(value || '')
        .split(/[\\n,;]+/)
        .map((item) => item.trim())
        .filter(Boolean);
    }

    function escapeHtml(value) {
      return String(value || '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    function formatDate(ts) {
      if (!ts) {
        return 'ещё не запускался';
      }
      const date = new Date(Number(ts) * 1000);
      if (Number.isNaN(date.getTime())) {
        return 'ещё не запускался';
      }
      return date.toLocaleString('ru-RU');
    }

    function showMessage(text, type) {
      const box = els.messageBox;
      if (!text) {
        box.className = 'message';
        box.textContent = '';
        return;
      }
      box.className = 'message ' + (type || 'info');
      box.textContent = text;
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    async function api(path, options = {}) {
      const headers = Object.assign({}, options.headers || {});
      if (state.authToken) {
        headers['x-admin-token'] = state.authToken;
      }
      if (options.body && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
      }
      const response = await fetch(path, Object.assign({}, options, { headers }));
      let payload = {};
      try {
        payload = await response.json();
      } catch (error) {
        payload = {};
      }
      if (!response.ok || payload.ok === false) {
        const message = payload.error || ('HTTP ' + response.status);
        throw new Error(message);
      }
      return payload;
    }

    function renderSelect(selectEl, items, selectedValue) {
      selectEl.innerHTML = items.map((item) => {
        const selected = String(item.id) === String(selectedValue) ? ' selected' : '';
        return '<option value="' + escapeHtml(item.id) + '"' + selected + '>' + escapeHtml(item.label) + '</option>';
      }).join('');
    }

    function renderMultiSelect(selectEl, items, selectedValues) {
      const selectedSet = new Set((selectedValues || []).map(String));
      selectEl.innerHTML = items.map((item) => {
        const selected = selectedSet.has(String(item.id)) ? ' selected' : '';
        return '<option value="' + escapeHtml(item.id) + '"' + selected + '>' + escapeHtml(item.label) + '</option>';
      }).join('');
    }

    function renderCheckGroup(container, items, selectedValues) {
      const selected = new Set((selectedValues || []).map(String));
      container.innerHTML = items.map((item) => {
        const checked = selected.has(String(item.id)) ? ' checked' : '';
        return (
          '<label class="check-pill">' +
            '<input type="checkbox" value="' + escapeHtml(item.id) + '"' + checked + '>' +
            '<span>' + escapeHtml(item.label) + '</span>' +
          '</label>'
        );
      }).join('');
    }

    function readCheckedValues(container) {
      return Array.from(container.querySelectorAll('input[type="checkbox"]:checked')).map((input) => input.value);
    }

    function currentTemplates() {
      return (state.data && state.data.templates) || [];
    }

    function getSelectedTemplate() {
      return currentTemplates().find((item) => item.id === state.selectedTemplateId) || null;
    }

    function renderLoadError(error) {
      const errorText = error && error.message ? error.message : 'Не удалось загрузить данные';
      els.statusSearch.textContent = 'Ошибка загрузки';
      els.statusTemplate.textContent = 'Проверьте соединение';
      els.statusChat.textContent = 'Данные недоступны';
      els.statusLastCheck.textContent = 'Данные недоступны';
      els.areaHint.textContent = 'Если страница открылась, а данные не подгрузились, значит не ответил API панели.';
      els.templateList.innerHTML = '<div class="empty-sidebar">Не удалось загрузить список сценариев.</div>';
      els.currentSummary.innerHTML = '';
      els.resultsMeta.textContent = 'Данные не загружены.';
      els.resultsList.innerHTML = '<div class="hint">После исправления ошибки нажмите «Обновить данные».</div>';
      els.resultsPage.textContent = '';
      els.resultsPrev.disabled = true;
      els.resultsNext.disabled = true;
      showMessage(errorText, 'error');
    }

    function renderStatus() {
      const status = state.data.status;
      els.statusSearch.textContent = status.searching ? 'Автопоиск включён' : 'Автопоиск на паузе';
      els.statusTemplate.textContent = status.active_template_name || 'не выбран';
      els.statusChat.textContent = status.chat_configured ? 'Чат подключён' : 'Чат ещё не подключён';
      els.statusLastCheck.textContent = formatDate(status.last_check);
      els.toggleBtn.textContent = status.searching ? 'Поставить на паузу' : 'Включить автопоиск';
      els.areaHint.textContent = 'Подсказка: популярные регионы для быстрого ввода — ' + state.data.options.popular_areas.join(', ');
    }

    function renderTemplateList() {
      const templates = currentTemplates();
      if (!templates.length) {
        els.templateList.innerHTML = '<div class="empty-sidebar">Сохранённых сценариев пока нет.</div>';
        return;
      }
      els.templateList.innerHTML = templates.map((template) => {
        const isActive = template.id === state.data.active_template_id;
        const isSelected = template.id === state.selectedTemplateId;
        const classes = ['template-card'];
        if (isActive || isSelected) {
          classes.push('active');
        }
        const meta = [
          'Запросов: ' + template.queries.length,
          'Интервал: ' + template.interval + ' мин',
          'Страниц: ' + template.max_pages,
          'На странице: ' + template.delivery_page_size,
          isActive ? 'Сейчас автопоиск использует этот сценарий' : 'Сохранён для ручного запуска'
        ].join('\\n');
        return (
          '<div class="' + classes.join(' ') + '">' +
            '<div>' +
              '<h4>' + escapeHtml(template.name) + '</h4>' +
              '<div class="template-meta">' + escapeHtml(meta) + '</div>' +
            '</div>' +
            '<div class="actions">' +
              '<button class="ghost" type="button" onclick="selectTemplate(\\'' + template.id + '\\')">Открыть</button>' +
              '<button class="ghost" type="button" onclick="activateTemplate(\\'' + template.id + '\\')">' + (isActive ? 'Активен' : 'Сделать активным') + '</button>' +
              '<button class="danger" type="button" onclick="deleteTemplate(\\'' + template.id + '\\')">Удалить</button>' +
            '</div>' +
          '</div>'
        );
      }).join('');
    }

    function fillForm(template) {
      const options = state.data.options;
      const current = template || state.data.new_template;
      state.selectedTemplateId = current.id || '';

      els.name.value = current.name || '';
      els.queries.value = (current.queries || []).join('\\n');
      renderMultiSelect(els.searchFields, options.search_fields, current.search_fields || []);
      renderCheckGroup(els.experienceGroup, options.experience, current.experience || []);
      els.includedAreas.value = (current.included_area_names || []).join('\\n');
      els.excludedAreas.value = (current.excluded_area_names || []).join('\\n');
      els.includeKeywords.value = (current.include_keywords || []).join('\\n');
      els.excludeKeywords.value = (current.exclude_keywords || []).join('\\n');
      els.includeIn.value = current.include_in || 'both';
      els.excludeIn.value = current.exclude_in || 'both';
      els.excludedEmployers.value = (current.excluded_employers || []).join('\\n');
      renderCheckGroup(els.workFormatsGroup, options.work_formats, current.work_formats || []);
      renderCheckGroup(els.employmentGroup, options.employment_types, current.employment_types || []);
      els.onlyWithSalary.checked = !!current.only_with_salary;
      els.salaryMin.value = current.salary_min || 0;
      renderSelect(els.sort, options.sort, current.sort || 'publication_time');
      renderSelect(els.periodDays, options.period_days, current.period_days || 1);
      els.maxPages.value = current.max_pages || 5;
      els.maxResults.value = current.max_results || 50;
      els.deliveryPageSize.value = current.delivery_page_size || 5;
      els.interval.value = current.interval || 30;
      els.currentSummary.innerHTML = current.summary_html || '';
    }

    function gatherForm() {
      return {
        id: state.selectedTemplateId || '',
        name: els.name.value.trim(),
        queries: splitValues(els.queries.value),
        search_fields: Array.from(els.searchFields.selectedOptions).map((option) => option.value),
        experience: readCheckedValues(els.experienceGroup),
        included_area_names: splitValues(els.includedAreas.value),
        excluded_area_names: splitValues(els.excludedAreas.value),
        include_keywords: splitValues(els.includeKeywords.value),
        include_in: els.includeIn.value,
        exclude_keywords: splitValues(els.excludeKeywords.value),
        exclude_in: els.excludeIn.value,
        work_formats: readCheckedValues(els.workFormatsGroup),
        employment_types: readCheckedValues(els.employmentGroup),
        only_with_salary: els.onlyWithSalary.checked,
        salary_min: els.salaryMin.value,
        excluded_employers: splitValues(els.excludedEmployers.value),
        sort: els.sort.value,
        period_days: els.periodDays.value,
        max_pages: els.maxPages.value,
        max_results: els.maxResults.value,
        delivery_page_size: els.deliveryPageSize.value,
        interval: els.interval.value
      };
    }

    function renderResults() {
      const result = state.result;
      if (!result) {
        els.resultsMeta.textContent = 'Нажмите «Проверить вакансии» или «Предпросмотр выдачи».';
        els.resultsList.innerHTML = '';
        els.resultsPage.textContent = '';
        els.resultsPrev.disabled = true;
        els.resultsNext.disabled = true;
        return;
      }

      const pageSize = Math.max(1, Number(result.page_size || 5));
      const vacancies = result.vacancies || [];
      const pageCount = Math.max(1, Math.ceil(vacancies.length / pageSize));
      if (state.resultPage >= pageCount) {
        state.resultPage = pageCount - 1;
      }
      if (state.resultPage < 0) {
        state.resultPage = 0;
      }
      const start = state.resultPage * pageSize;
      const pageItems = vacancies.slice(start, start + pageSize);
      const parts = [
        (result.persist ? 'Проверка' : 'Предпросмотр') + ': ' + result.template_name,
        'Показано: ' + result.shown_count,
        'Всего найдено: ' + result.total_found
      ];
      if (result.reason) {
        parts.push(result.reason);
      }
      if (result.errors && result.errors.length) {
        parts.push('Ошибки: ' + result.errors.slice(0, 2).join('; '));
      }
      els.resultsMeta.textContent = parts.join(' · ');

      if (!pageItems.length) {
        els.resultsList.innerHTML = '<div class="hint">Нет вакансий для отображения.</div>';
      } else {
        els.resultsList.innerHTML = pageItems.map((vacancy, index) => {
          const number = start + index + 1;
          const meta = [
            vacancy.employer,
            vacancy.area
          ].filter(Boolean).join(' · ');
          const extra = [
            vacancy.experience ? 'Опыт: ' + vacancy.experience : '',
            vacancy.salary ? 'Зарплата: ' + vacancy.salary : '',
            vacancy.work_formats && vacancy.work_formats.length ? 'Формат: ' + vacancy.work_formats.join(', ') : '',
            vacancy.schedule ? 'График: ' + vacancy.schedule : ''
          ].filter(Boolean).join(' · ');
          return (
            '<article class="result-card">' +
              '<h4>' + number + '. ' + escapeHtml(vacancy.name) + '</h4>' +
              '<div class="result-meta">' + escapeHtml(meta) + '</div>' +
              '<div class="result-meta">' + escapeHtml(extra) + '</div>' +
              (vacancy.snippet ? '<div>' + escapeHtml(vacancy.snippet) + '</div>' : '') +
              (vacancy.url ? '<div><a href="' + escapeHtml(vacancy.url) + '" target="_blank" rel="noreferrer">Открыть вакансию на hh.ru</a></div>' : '') +
            '</article>'
          );
        }).join('');
      }

      els.resultsPage.textContent = 'Страница ' + (state.resultPage + 1) + ' из ' + pageCount;
      els.resultsPrev.disabled = state.resultPage <= 0;
      els.resultsNext.disabled = state.resultPage >= pageCount - 1;
    }

    function renderAll() {
      renderStatus();
      renderTemplateList();
      fillForm(getSelectedTemplate() || state.data.active_template || state.data.new_template);
      renderResults();
    }

    async function loadState(preferredTemplateId) {
      const payload = await api('/api/web-state');
      state.data = payload.state;
      const templateIds = new Set(currentTemplates().map((item) => item.id));
      if (preferredTemplateId && templateIds.has(preferredTemplateId)) {
        state.selectedTemplateId = preferredTemplateId;
      } else if (state.selectedTemplateId && templateIds.has(state.selectedTemplateId)) {
        // keep current selection
      } else if (state.data.active_template) {
        state.selectedTemplateId = state.data.active_template.id;
      } else if (currentTemplates()[0]) {
        state.selectedTemplateId = currentTemplates()[0].id;
      } else {
        state.selectedTemplateId = state.data.new_template.id;
      }
      renderAll();
    }

    async function saveTemplate(activate) {
      const payload = await api('/api/web-template-save', {
        method: 'POST',
        body: JSON.stringify({
          template: gatherForm(),
          activate: !!activate
        })
      });
      state.result = null;
      state.resultPage = 0;
      await loadState(payload.template.id);
      const messages = [];
      if (payload.warnings && payload.warnings.length) {
        messages.push(payload.warnings.join('\\n'));
      }
      messages.unshift('Сценарий сохранён.');
      showMessage(messages.join('\\n'), payload.warnings && payload.warnings.length ? 'info' : 'success');
    }

    async function activateTemplate(id) {
      const targetId = id || state.selectedTemplateId;
      if (!targetId) {
        showMessage('Сначала сохраните поиск.', 'error');
        return;
      }
      await api('/api/web-template-activate?template_id=' + encodeURIComponent(targetId), { method: 'POST' });
      state.result = null;
      state.resultPage = 0;
      await loadState(targetId);
      showMessage('Активный сценарий обновлён.', 'success');
    }

    async function deleteTemplate(id) {
      const targetId = id || state.selectedTemplateId;
      if (!targetId) {
        showMessage('Нет выбранного поиска для удаления.', 'error');
        return;
      }
      if (!window.confirm('Удалить этот поиск?')) {
        return;
      }
      await api('/api/web-template-delete?template_id=' + encodeURIComponent(targetId), { method: 'POST' });
      state.result = null;
      state.resultPage = 0;
      await loadState();
      showMessage('Сценарий удалён.', 'success');
    }

    async function resetSent() {
      const targetId = state.selectedTemplateId;
      if (!targetId) {
        showMessage('Сначала сохраните или выберите поиск.', 'error');
        return;
      }
      await api('/api/web-template-reset-sent?template_id=' + encodeURIComponent(targetId), { method: 'POST' });
      await loadState(targetId);
      showMessage('История отправленных вакансий очищена.', 'success');
    }

    async function toggleSearching() {
      const nextStatus = !state.data.status.searching;
      await api('/api/web-searching', {
        method: 'POST',
        body: JSON.stringify({ searching: nextStatus })
      });
      await loadState(state.selectedTemplateId);
      showMessage(nextStatus ? 'Автопоиск включён.' : 'Автопоиск поставлен на паузу.', 'success');
    }

    async function runSearch(persist) {
      const form = gatherForm();
      if (persist && !form.id) {
        showMessage('Сначала сохраните поиск, потом запускайте обычный режим.', 'error');
        return;
      }
      const path = persist ? '/api/web-search-run' : '/api/web-search-preview';
      const payload = await api(path, {
        method: 'POST',
        body: JSON.stringify({
          template_id: form.id || '',
          template: persist ? null : form
        })
      });
      state.result = payload.result;
      state.resultPage = 0;
      state.data = payload.state;
      if (payload.template && payload.template.id) {
        state.selectedTemplateId = payload.template.id;
      }
      renderAll();
      if (payload.result.reason) {
        showMessage(payload.result.reason, payload.result.errors && payload.result.errors.length ? 'error' : 'info');
      } else {
        showMessage((persist ? 'Проверка' : 'Предпросмотр') + ' завершена. Найдено к показу: ' + payload.result.shown_count, 'success');
      }
    }

    function selectTemplate(id) {
      state.result = null;
      state.resultPage = 0;
      state.selectedTemplateId = id;
      renderAll();
      showMessage('', 'info');
    }

    function createNewTemplate() {
      state.result = null;
      state.resultPage = 0;
      state.selectedTemplateId = state.data.new_template.id;
      fillForm(state.data.new_template);
      renderTemplateList();
      renderResults();
      showMessage('Открыт чистый сценарий. Заполните поля и сохраните его.', 'info');
    }

    function bindEvents() {
      els.refreshBtn.addEventListener('click', () => loadState(state.selectedTemplateId).then(() => showMessage('Данные обновлены.', 'success')).catch((error) => showMessage(error.message, 'error')));
      els.toggleBtn.addEventListener('click', () => toggleSearching().catch((error) => showMessage(error.message, 'error')));
      els.runBtn.addEventListener('click', () => runSearch(true).catch((error) => showMessage(error.message, 'error')));
      els.previewBtn.addEventListener('click', () => runSearch(false).catch((error) => showMessage(error.message, 'error')));
      els.newSearchBtn.addEventListener('click', createNewTemplate);
      els.saveBtn.addEventListener('click', () => saveTemplate(false).catch((error) => showMessage(error.message, 'error')));
      els.saveActivateBtn.addEventListener('click', () => saveTemplate(true).catch((error) => showMessage(error.message, 'error')));
      els.activateBtn.addEventListener('click', () => activateTemplate().catch((error) => showMessage(error.message, 'error')));
      els.deleteBtn.addEventListener('click', () => deleteTemplate().catch((error) => showMessage(error.message, 'error')));
      els.resetSentBtn.addEventListener('click', () => resetSent().catch((error) => showMessage(error.message, 'error')));
      els.resultsPrev.addEventListener('click', () => {
        state.resultPage -= 1;
        renderResults();
      });
      els.resultsNext.addEventListener('click', () => {
        state.resultPage += 1;
        renderResults();
      });
      els.saveTokenBtn.addEventListener('click', async () => {
        state.authToken = els.authToken.value.trim();
        localStorage.setItem('hh_web_admin_token', state.authToken);
        try {
          await loadState(state.selectedTemplateId);
          showMessage('Токен сохранён.', 'success');
        } catch (error) {
          showMessage(error.message, 'error');
        }
      });
    }

    async function init() {
      els.messageBox = qs('messageBox');
      els.tokenBox = qs('tokenBox');
      els.authToken = qs('authToken');
      els.saveTokenBtn = qs('saveTokenBtn');
      els.statusSearch = qs('statusSearch');
      els.statusTemplate = qs('statusTemplate');
      els.statusChat = qs('statusChat');
      els.statusLastCheck = qs('statusLastCheck');
      els.toggleBtn = qs('toggleBtn');
      els.refreshBtn = qs('refreshBtn');
      els.runBtn = qs('runBtn');
      els.previewBtn = qs('previewBtn');
      els.newSearchBtn = qs('newSearchBtn');
      els.templateList = qs('templateList');
      els.name = qs('name');
      els.queries = qs('queries');
      els.searchFields = qs('searchFields');
      els.experienceGroup = qs('experienceGroup');
      els.includedAreas = qs('includedAreas');
      els.excludedAreas = qs('excludedAreas');
      els.areaHint = qs('areaHint');
      els.includeKeywords = qs('includeKeywords');
      els.excludeKeywords = qs('excludeKeywords');
      els.includeIn = qs('includeIn');
      els.excludeIn = qs('excludeIn');
      els.excludedEmployers = qs('excludedEmployers');
      els.workFormatsGroup = qs('workFormatsGroup');
      els.employmentGroup = qs('employmentGroup');
      els.onlyWithSalary = qs('onlyWithSalary');
      els.salaryMin = qs('salaryMin');
      els.sort = qs('sort');
      els.periodDays = qs('periodDays');
      els.maxPages = qs('maxPages');
      els.maxResults = qs('maxResults');
      els.deliveryPageSize = qs('deliveryPageSize');
      els.interval = qs('interval');
      els.saveBtn = qs('saveBtn');
      els.saveActivateBtn = qs('saveActivateBtn');
      els.activateBtn = qs('activateBtn');
      els.resetSentBtn = qs('resetSentBtn');
      els.deleteBtn = qs('deleteBtn');
      els.currentSummary = qs('currentSummary');
      els.resultsMeta = qs('resultsMeta');
      els.resultsList = qs('resultsList');
      els.resultsPrev = qs('resultsPrev');
      els.resultsNext = qs('resultsNext');
      els.resultsPage = qs('resultsPage');

      if (TOKEN_REQUIRED) {
        els.tokenBox.classList.add('visible');
      }
      if (state.authToken) {
        els.authToken.value = state.authToken;
      }

      bindEvents();
      try {
        await loadState();
        showMessage('Панель готова к работе.', 'success');
      } catch (error) {
        renderLoadError(error);
      }
    }

    window.selectTemplate = selectTemplate;
    window.activateTemplate = activateTemplate;
    window.deleteTemplate = deleteTemplate;
    window.addEventListener('DOMContentLoaded', init);
  </script>
</body>
</html>
'''.replace("__TOKEN_REQUIRED__", token_required)


if FastAPI is not None:
    app = FastAPI(title="HH Vacancy Bot")

    def _web_unauthorized_response():
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)

    async def _read_request_json(request: Request):
        try:
            return await request.json()
        except Exception:
            return {}

    @app.get("/")
    @app.get("/ui")
    @app.get("/index")
    @app.get("/index.html")
    @app.get("/api/ui")
    def api_root():
        return HTMLResponse(_web_ui_html())

    @app.get("/health")
    @app.get("/api/health")
    def api_health():
        return {
            **_build_runtime_status(),
            "message": "HH bot is alive",
        }

    @app.get("/status")
    @app.get("/api/status")
    def api_status():
        return _build_runtime_status()

    @app.get("/api/web/state")
    @app.get("/api/web-state")
    def api_web_state(request: Request):
        if not _web_request_authorized(request):
            return _web_unauthorized_response()
        data = load_data()
        return {"ok": True, "state": _build_web_state(data)}

    @app.post("/api/web/template/save")
    @app.post("/api/web-template-save")
    async def api_web_template_save(request: Request):
        if not _web_request_authorized(request):
            return _web_unauthorized_response()
        payload = await _read_request_json(request)
        data = load_data()
        template, warnings = _build_template_from_payload(payload.get("template") or {})
        activate = _coerce_bool(payload.get("activate"))
        template = _upsert_template(data, template, activate=activate)
        _ensure_templates_ready(data)
        save_data(data)
        return {
            "ok": True,
            "warnings": warnings,
            "template": _template_to_web_payload(template),
            "state": _build_web_state(data),
        }

    @app.post("/api/web/template/{template_id}/activate")
    @app.post("/api/web-template-activate")
    def api_web_template_activate(request: Request, template_id: str = ""):
        if not _web_request_authorized(request):
            return _web_unauthorized_response()
        data = load_data()
        tmpl = next((item for item in data.get("templates", []) if item.get("id") == template_id), None)
        if not tmpl:
            return JSONResponse({"ok": False, "error": "Поиск не найден"}, status_code=404)
        data["active_template_id"] = template_id
        data.setdefault("sent_ids_by_template", {}).setdefault(str(template_id), [])
        save_data(data)
        return {"ok": True, "state": _build_web_state(data)}

    @app.post("/api/web/template/{template_id}/reset-sent")
    @app.post("/api/web-template-reset-sent")
    def api_web_template_reset_sent(request: Request, template_id: str = ""):
        if not _web_request_authorized(request):
            return _web_unauthorized_response()
        data = load_data()
        tmpl = next((item for item in data.get("templates", []) if item.get("id") == template_id), None)
        if not tmpl:
            return JSONResponse({"ok": False, "error": "Поиск не найден"}, status_code=404)
        _set_template_sent_ids(data, template_id, [])
        save_data(data)
        return {"ok": True, "state": _build_web_state(data)}

    @app.delete("/api/web/template/{template_id}")
    @app.post("/api/web-template-delete")
    def api_web_template_delete(request: Request, template_id: str = ""):
        if not _web_request_authorized(request):
            return _web_unauthorized_response()
        data = load_data()
        before = len(data.get("templates", []))
        data["templates"] = [item for item in data.get("templates", []) if item.get("id") != template_id]
        if len(data["templates"]) == before:
            return JSONResponse({"ok": False, "error": "Поиск не найден"}, status_code=404)
        data.get("sent_ids_by_template", {}).pop(str(template_id), None)
        if data.get("active_template_id") == template_id:
            data["active_template_id"] = data["templates"][0]["id"] if data["templates"] else None
            data["searching"] = False
        _ensure_templates_ready(data)
        save_data(data)
        return {"ok": True, "state": _build_web_state(data)}

    @app.post("/api/web/searching")
    @app.post("/api/web-searching")
    async def api_web_searching(request: Request):
        if not _web_request_authorized(request):
            return _web_unauthorized_response()
        payload = await _read_request_json(request)
        data = load_data()
        if not _active_template(data):
            return JSONResponse({"ok": False, "error": "Нет активного сценария"}, status_code=400)
        data["searching"] = _coerce_bool(payload.get("searching"))
        save_data(data)
        return {"ok": True, "state": _build_web_state(data)}

    @app.post("/api/web/search/run")
    @app.post("/api/web-search-run")
    async def api_web_search_run(request: Request):
        if not _web_request_authorized(request):
            return _web_unauthorized_response()
        payload = await _read_request_json(request)
        data = load_data()
        template_id = str(payload.get("template_id") or "").strip()
        tmpl = next((item for item in data.get("templates", []) if item.get("id") == template_id), None)
        if not tmpl:
            return JSONResponse({"ok": False, "error": "Сначала сохраните поиск, потом запускайте обычный режим"}, status_code=400)
        result = _web_search_response(data, tmpl, persist=True)
        save_data(data)
        return {
            "ok": True,
            "template": _template_to_web_payload(tmpl),
            "result": result,
            "state": _build_web_state(data),
        }

    @app.post("/api/web/search/preview")
    @app.post("/api/web-search-preview")
    async def api_web_search_preview(request: Request):
        if not _web_request_authorized(request):
            return _web_unauthorized_response()
        payload = await _read_request_json(request)
        data = load_data()
        template_payload = payload.get("template") or {}
        template_id = str(payload.get("template_id") or "").strip()
        warnings = []
        if template_payload:
            tmpl, warnings = _build_template_from_payload(template_payload)
        elif template_id:
            tmpl = next((item for item in data.get("templates", []) if item.get("id") == template_id), None)
            if tmpl is None:
                return JSONResponse({"ok": False, "error": "Поиск не найден"}, status_code=404)
        else:
            return JSONResponse({"ok": False, "error": "Нет данных для предпросмотра"}, status_code=400)
        result = _web_search_response(data, tmpl, persist=False)
        return {
            "ok": True,
            "warnings": warnings,
            "template": _template_to_web_payload(tmpl),
            "result": result,
            "state": _build_web_state(data),
        }

    @app.get("/webhook-info")
    @app.get("/webhook/info")
    @app.get("/api/webhook-info")
    @app.get("/api/webhook/info")
    def api_webhook_info(request: Request):
        if not TG_API:
            return JSONResponse(
                {"ok": False, "error": "BOT_TOKEN missing", "status": _build_runtime_status()},
                status_code=500,
            )
        return {
            "ok": True,
            "target": get_telegram_webhook_target(request),
            "telegram": get_webhook_info(),
            "status": _build_runtime_status(),
        }

    @app.get("/webhook-register")
    @app.get("/webhook/register")
    @app.get("/api/webhook-register")
    @app.get("/api/webhook/register")
    def api_register_webhook(request: Request):
        if not TG_API:
            return JSONResponse(
                {"ok": False, "error": "BOT_TOKEN missing", "status": _build_runtime_status()},
                status_code=500,
            )

        target = get_telegram_webhook_target(request)
        if not target:
            return JSONResponse({"ok": False, "error": "Cannot resolve public webhook URL"}, status_code=400)

        response = set_webhook(target)
        status_code = 200 if response.get("ok") else 500
        return JSONResponse(
            {
                "ok": bool(response.get("ok")),
                "target": target,
                "telegram": response,
                "status": _build_runtime_status(),
            },
            status_code=status_code,
        )

    @app.post("/telegram-webhook")
    @app.post("/telegram/webhook")
    @app.post("/api/telegram-webhook")
    @app.post("/api/telegram/webhook")
    async def api_telegram_webhook(request: Request):
        try:
            update = await request.json()
        except Exception as e:
            print(f"❌ Некорректный webhook payload: {e}")
            return JSONResponse({"ok": False, "error": "bad request"}, status_code=400)

        try:
            process_update(update)
        except Exception as e:
            print(f"❌ Ошибка обработки webhook update: {e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        return {"ok": True}

    @app.get("/cron")
    @app.get("/api/cron")
    def api_cron(request: Request, force: int = 0, secret: str = ""):
        auth_header = request.headers.get("authorization", "")
        if not _cron_request_authorized(auth_header, secret):
            return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
        return run_scheduled_search_tick(force=bool(force))

    @app.get("/run-now")
    @app.get("/api/run-now")
    def api_run_now(request: Request, persist: int = 1, secret: str = ""):
        auth_header = request.headers.get("authorization", "")
        if not _cron_request_authorized(auth_header, secret):
            return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
        return run_manual_search_tick(persist=bool(persist))
else:
    app = None


class TelegramWebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"HH bot webhook is alive")

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            update = json.loads(raw_body.decode("utf-8"))
        except Exception as e:
            print(f"❌ Некорректный webhook payload: {e}")
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"bad request")
            return

        try:
            process_update(update)
        except Exception as e:
            print(f"❌ Ошибка обработки webhook update: {e}")

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):
        return


def run_polling():
    print("✅ Режим: polling")
    print("✅ Готов. Отправьте /start боту в Telegram.")
    delete_webhook(drop_pending_updates=False)
    offset = 0

    while True:
        try:
            updates = get_updates(offset)
        except Exception as e:
            print(f"❌ Ошибка получения обновлений: {e}")
            time.sleep(5)
            continue

        for upd in updates:
            offset = upd["update_id"] + 1
            process_update(upd)

        run_scheduled_search_tick()
        time.sleep(1)


def run_webhook():
    print("✅ Режим: webhook")
    target = get_telegram_webhook_target()
    response = set_webhook(target)
    if not response.get("ok"):
        print(f"❌ Не удалось зарегистрировать webhook: {response}")
    else:
        print(f"✅ Webhook зарегистрирован: {target}")

    server = ThreadingHTTPServer((WEBHOOK_HOST, WEBHOOK_PORT), TelegramWebhookHandler)
    server.timeout = 1
    print(f"✅ Локальный webhook-сервер слушает {WEBHOOK_HOST}:{WEBHOOK_PORT}")

    while True:
        server.handle_request()
        run_scheduled_search_tick()


def main():
    ensure_bot_token()
    bootstrap_bot()
    if USE_WEBHOOK:
        run_webhook()
    run_polling()


if __name__ == "__main__":
    main()
