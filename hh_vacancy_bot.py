#!/usr/bin/env python3
"""
HH.ru Smart Vacancy Bot v2
===========================
Полноценный Telegram-бот для поиска вакансий на hh.ru.
Настройка поиска прямо через Telegram — без редактирования кода.

Команды:
  /menu      — главное меню
  /start     — приветствие и помощь
  /new       — создать новый поисковый шаблон (wizard)
  /templates — список шаблонов, выбор/редактирование/удаление
  /current   — показать активный шаблон
  /run       — запустить поиск прямо сейчас (не ждать таймер)
  /preview   — предпросмотр без сохранения истории
  /clone     — копия активного шаблона
  /reset_sent — сброс истории отправок текущего шаблона
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
    from fastapi.responses import JSONResponse
except Exception:
    FastAPI = None
    Request = None
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
    tmpl["sort"] = tmpl.get("sort", "publication_time")
    tmpl["interval"] = int(tmpl.get("interval", 30) or 30)
    tmpl["max_pages"] = int(tmpl.get("max_pages", 5) or 5)
    tmpl["name"] = (tmpl.get("name") or "Новый шаблон")[:50]
    tmpl["id"] = str(tmpl.get("id") or str(uuid.uuid4())[:8])

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
    }

    state_map = normalized["user_states"]
    for chat_id, state in list(state_map.items()):
        if not isinstance(state, dict):
            state_map.pop(chat_id, None)
            continue
        if "draft" in state:
            state["draft"] = _normalize_template(state.get("draft", {}))

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
                    data = r.json()
                except Exception as e:
                    print(f"❌ Ошибка запроса hh.ru: {e}")
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
    return sorted_final[:max_results]


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

    include_text = ", ".join(_esc(name) for name in include_names) if include_names else "Все страны и города"
    exclude_text = ", ".join(_esc(name) for name in exclude_names) if exclude_names else "Без исключений"
    include_kw_preview = ", ".join(_esc(word) for word in include_kw[:6]) or "нет"
    exclude_kw_preview = ", ".join(_esc(word) for word in exclude_kw[:6]) or "нет"
    if len(include_kw) > 6:
        include_kw_preview += f" ... (+{len(include_kw) - 6})"
    if len(exclude_kw) > 6:
        exclude_kw_preview += f" ... (+{len(exclude_kw) - 6})"

    lines = [
        f"<b>{_esc(template.get('name', 'Новый шаблон'))}</b>",
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
    }
    save_data(data)

    send_msg(
        chat_id,
        "<b>Мастер настройки поиска</b>\n\n"
        "<b>Запросы</b>\n"
        "Введите названия вакансий через запятую.\n"
        "Или напишите <code>default</code> для полного набора аналитических должностей и синонимов.\n\n"
        "Пример: <code>data analyst, product analyst, business analyst</code>\n\n"
        "Дальше я пошагово спрошу опыт, географию, слова, формат работы, зарплату и другие фильтры."
    )

def _new_draft():
    return _normalize_template({
        "id":               str(uuid.uuid4())[:8],
        "name":             "Новый шаблон",
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
        state["step"] = "search_fields"
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
        state["step"] = "exclude_areas"
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
        state["step"] = "include_kw"
        save_data(data)
        _send_include_kw_prompt(chat_id)
        return True

    if step == "include_kw":
        lo = txt.lower()
        if lo in SKIP_WORDS:
            draft["include_keywords"] = []
            state["step"] = "exclude_kw"
            save_data(data)
            _send_exclude_kw_prompt(chat_id)
            return True

        draft["include_keywords"] = [k.strip().lower() for k in txt.split(",") if k.strip()]
        if not draft["include_keywords"]:
            send_msg(chat_id, "Введите слова через запятую или напишите <code>нет</code>.")
            return True
        state["step"] = "include_in"
        save_data(data)
        _send_include_in_kb(chat_id)
        return True

    if step == "exclude_kw":
        lo = txt.lower()
        if lo == "default":
            draft["exclude_keywords"] = DEFAULT_EXCLUDE_KEYWORDS[:]
        elif lo in SKIP_WORDS:
            draft["exclude_keywords"] = []
            state["step"] = "work_formats"
            save_data(data)
            _send_work_formats_kb(chat_id, draft.get("work_formats", []))
            return True

        draft["exclude_keywords"] = [k.strip().lower() for k in txt.split(",") if k.strip()]
        if not draft["exclude_keywords"]:
            send_msg(chat_id, "Введите слова через запятую, <code>default</code> или <code>нет</code>.")
            return True
        state["step"] = "exclude_in"
        save_data(data)
        _send_exclude_in_kb(chat_id)
        return True

    if step == "salary_min":
        value = re.sub(r"[^0-9]", "", txt)
        if not value:
            send_msg(chat_id, "Введите число, например <code>120000</code>, или вернитесь назад через /new.")
            return True
        draft["only_with_salary"] = True
        draft["salary_min"] = int(value)
        state["step"] = "employers"
        save_data(data)
        _send_employers_prompt(chat_id)
        return True

    if step == "employers":
        lo = txt.lower()
        if lo in SKIP_WORDS:
            draft["excluded_employers"] = []
        else:
            draft["excluded_employers"] = [item.strip().lower() for item in txt.split(",") if item.strip()]
        state["step"] = "sort"
        save_data(data)
        _send_sort_kb(chat_id)
        return True

    if step == "name":
        if txt.lower() not in ("ok", "ок"):
            draft["name"] = txt[:50]
        state["step"] = "confirm"
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
    send_msg(chat_id, "<b>Где искать совпадения</b>\nВыберите одно или несколько полей:", reply_markup={"inline_keyboard": buttons})

def _send_experience_kb(chat_id, selected):
    buttons = []
    for code, label in EXPERIENCE_OPTIONS.items():
        mark = "[x] " if code in selected else "[ ] "
        buttons.append([{"text": mark + label, "callback_data": f"exp_{code}"}])
    buttons.append([{"text": "Далее", "callback_data": "exp_done"}])
    send_msg(chat_id, "<b>Опыт работы</b>\nВыберите один или несколько вариантов:",
             reply_markup={"inline_keyboard": buttons})

def _send_area_scope_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": "Искать везде", "callback_data": "scope_all"}],
        [{"text": "Искать только в выбранных странах/городах", "callback_data": "scope_selected"}],
    ]}
    send_msg(chat_id, "<b>География поиска</b>\nСначала выберите общий режим:", reply_markup=kb)

def _send_include_area_prompt(chat_id):
    examples = ", ".join(POPULAR_AREA_NAMES[:12])
    send_msg(
        chat_id,
        "<b>Страны / города для включения</b>\n"
        "Введите через запятую.\n\n"
        f"Примеры: {examples}\n\n"
        "Пример: <code>Грузия, Тбилиси, Беларусь</code>"
    )

def _send_exclude_area_prompt(chat_id):
    send_msg(
        chat_id,
        "<b>Страны / города для исключения</b>\n"
        "Введите через запятую или <code>нет</code>, если исключений не нужно.\n\n"
        "Примеры:\n"
        "<code>Москва</code>\n"
        "<code>Москва, Минск</code>\n"
        "<code>Россия</code>"
    )

def _send_include_kw_prompt(chat_id):
    send_msg(
        chat_id,
        "<b>Слова, которые должны присутствовать</b>\n"
        "Введите через запятую или <code>нет</code>, если такой фильтр не нужен.\n\n"
        "Пример: <code>sql, python, product</code>"
    )

def _send_include_in_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": "Искать только в названии", "callback_data": "ii_title"}],
        [{"text": "Искать только в описании", "callback_data": "ii_description"}],
        [{"text": "Искать и в названии, и в описании", "callback_data": "ii_both"}],
    ]}
    send_msg(chat_id, "<b>Где должны встречаться включающие слова</b>", reply_markup=kb)

def _send_exclude_kw_prompt(chat_id):
    send_msg(
        chat_id,
        "<b>Ключевые слова для исключения</b>\n\n"
        "• <code>default</code> — стандартный список (гемблинг, казино, беттинг и т.д.)\n"
        "• <code>нет</code>     — не фильтровать\n"
        "• Или введите свои слова через запятую\n\n"
        f"В дефолтном списке: <b>{len(DEFAULT_EXCLUDE_KEYWORDS)}</b> слов"
    )

def _send_exclude_in_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": "Только в названии", "callback_data": "ei_title"}],
        [{"text": "Только в описании", "callback_data": "ei_description"}],
        [{"text": "И в названии, и в описании", "callback_data": "ei_both"}],
    ]}
    send_msg(chat_id, "<b>Где применять фильтр слов</b>", reply_markup=kb)

def _work_formats_keyboard(selected):
    buttons = [[{"text": "Сбросить выбор (любой формат)", "callback_data": "wf_any"}]]
    for code, label in get_work_format_options().items():
        mark = "[x] " if code in selected else "[ ] "
        buttons.append([{"text": mark + label.replace("\xa0", " "), "callback_data": f"wf_{code}"}])
    buttons.append([{"text": "Далее", "callback_data": "wf_done"}])
    return buttons

def _send_work_formats_kb(chat_id, selected):
    send_msg(chat_id, "<b>Формат работы</b>\nВыберите один или несколько вариантов. Если ничего не выбрано, подойдут любые.", reply_markup={"inline_keyboard": _work_formats_keyboard(selected)})

def _employment_keyboard(selected):
    buttons = [[{"text": "Сбросить выбор (любая занятость)", "callback_data": "emp_any"}]]
    for code, label in get_employment_options().items():
        mark = "[x] " if code in selected else "[ ] "
        buttons.append([{"text": mark + label, "callback_data": f"emp_{code}"}])
    buttons.append([{"text": "Далее", "callback_data": "emp_done"}])
    return buttons

def _send_employment_kb(chat_id, selected):
    send_msg(chat_id, "<b>Тип занятости</b>\nВыберите один или несколько вариантов. Если ничего не выбрано, подойдут любые.", reply_markup={"inline_keyboard": _employment_keyboard(selected)})

def _send_salary_mode_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": "Без фильтра по зарплате", "callback_data": "sal_any"}],
        [{"text": "Только вакансии с зарплатой", "callback_data": "sal_only"}],
        [{"text": "Указать минимальную зарплату", "callback_data": "sal_min"}],
    ]}
    send_msg(chat_id, "<b>Фильтр по зарплате</b>", reply_markup=kb)

def _send_employers_prompt(chat_id):
    send_msg(
        chat_id,
        "<b>Работодатели для исключения</b>\n"
        "Введите компании через запятую или <code>нет</code>.\n\n"
        "Пример: <code>ANCOR, Lenkep recruitment</code>"
    )

def _send_sort_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": label, "callback_data": f"sort_{code}"}]
        for code, label in SORT_OPTIONS.items()
    ]}
    send_msg(chat_id, "<b>Сортировка</b>", reply_markup=kb)

def _send_period_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": label, "callback_data": f"period_{days}"}]
        for days, label in PERIOD_OPTIONS.items()
    ]}
    send_msg(chat_id, "<b>Период поиска</b>\nЗа какой период брать вакансии с hh.ru:", reply_markup=kb)

def _send_pages_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": label, "callback_data": f"pages_{pages}"}]
        for pages, label in MAX_PAGES_OPTIONS.items()
    ]}
    send_msg(chat_id, "<b>Глубина поиска</b>\nСколько страниц просматривать для каждого запроса:", reply_markup=kb)

def _send_max_results_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": label, "callback_data": f"limit_{limit}"}]
        for limit, label in MAX_RESULTS_OPTIONS.items()
    ]}
    send_msg(chat_id, "<b>Лимит за один запуск</b>\nСколько вакансий максимум отправлять за одну проверку:", reply_markup=kb)

def _send_interval_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": label, "callback_data": f"int_{mins}"}]
        for mins, label in INTERVAL_OPTIONS.items()
    ]}
    send_msg(chat_id, "<b>Интервал автопроверки</b>", reply_markup=kb)

def _send_confirm(chat_id, draft):
    text = _format_template_summary(draft, detailed=True)
    kb = {"inline_keyboard": [[
        {"text": "Сохранить", "callback_data": "confirm_save"},
        {"text": "Отмена",   "callback_data": "confirm_cancel"},
    ]]}
    send_msg(chat_id, text, reply_markup=kb)


# ═══════════════════════════════════════════════════════════
#  КОМАНДЫ БОТА
# ═══════════════════════════════════════════════════════════

def _menu_reply_markup():
    return {"inline_keyboard": [
        [{"text": "Новый поиск", "callback_data": "tmpl_new"},
         {"text": "Шаблоны", "callback_data": "menu_templates"}],
        [{"text": "Текущий шаблон", "callback_data": "menu_current"},
         {"text": "Поиск сейчас", "callback_data": "run_now"}],
        [{"text": "Предпросмотр", "callback_data": "preview_now"},
         {"text": "Пауза / запуск", "callback_data": "toggle"}],
        [{"text": "Клон шаблона", "callback_data": "clone_active"},
         {"text": "Сбросить историю", "callback_data": "reset_sent"}],
        [{"text": "Справка", "callback_data": "menu_help"}],
    ]}


def cmd_menu(chat_id, data):
    data["chat_id"] = chat_id
    save_data(data)
    send_msg(chat_id, "<b>Главное меню</b>\nВыберите действие:", reply_markup=_menu_reply_markup())


def cmd_start(chat_id, data):
    data["chat_id"] = chat_id
    save_data(data)
    send_msg(chat_id,
        "<b>HH.ru Vacancy Bot</b>\n\n"
        "Отслеживаю вакансии на hh.ru и присылаю новые по вашим критериям.\n\n"
        "<b>Команды:</b>\n"
        "/menu      — главное меню\n"
        "/new       — создать поисковый шаблон\n"
        "/templates — шаблоны (выбор/редактирование)\n"
        "/current   — показать активный шаблон\n"
        "/run       — запустить поиск прямо сейчас\n"
        "/preview   — предпросмотр без сохранения в историю\n"
        "/clone     — сделать копию активного шаблона\n"
        "/reset_sent — очистить историю отправок активного шаблона\n"
        "/toggle    — включить/выключить автопоиск\n"
        "/status    — статус и статистика\n"
        "/help      — подробная справка"
        ,
        reply_markup=_menu_reply_markup()
    )

def cmd_help(chat_id):
    send_msg(chat_id,
        "<b>Как пользоваться</b>\n\n"
        "1. <b>/new</b> — создайте шаблон через мастер\n"
        "2. <b>/templates</b> — выберите, отредактируйте, удалите или клонируйте шаблон\n"
        "3. <b>/run</b> — немедленно пришлю новые вакансии\n"
        "4. <b>/preview</b> — покажу результат без записи в историю\n"
        "5. <b>/toggle</b> — пауза или запуск автопоиска\n"
        "6. <b>/current</b> — полная сводка активного шаблона\n"
        "7. <b>/reset_sent</b> — очистка истории отправок активного шаблона\n\n"
        "<b>Доступные фильтры:</b>\n"
        "• География: страны и города на включение и исключение\n"
        "• Опыт: любые HH-варианты, можно несколько\n"
        "• Поля поиска: название, компания, описание\n"
        "• Включающие и исключающие слова\n"
        "• Формат работы и тип занятости\n"
        "• Только вакансии с зарплатой и минимальная зарплата\n"
        "• Исключение работодателей\n"
        "• Сортировка, глубина страниц, период и лимит результатов"
    )


def cmd_current(chat_id, data):
    data["chat_id"] = chat_id
    save_data(data)
    tmpl = _active_template(data)
    if not tmpl:
        send_msg(chat_id, "Нет активного шаблона. Создайте его через /new")
        return
    send_msg(chat_id, _format_template_summary(tmpl, detailed=True))


def _clone_template(data, tmpl):
    clone = _normalize_template(dict(tmpl))
    clone["id"] = str(uuid.uuid4())[:8]
    clone["name"] = f"{tmpl['name'][:38]} (копия)"[:50]
    data["templates"].append(clone)
    data["active_template_id"] = clone["id"]
    _set_template_sent_ids(data, clone["id"], [])
    return clone


def cmd_clone(chat_id, data):
    data["chat_id"] = chat_id
    tmpl = _active_template(data)
    if not tmpl:
        save_data(data)
        send_msg(chat_id, "Нет активного шаблона для копирования.")
        return

    clone = _clone_template(data, tmpl)
    save_data(data)

    send_msg(
        chat_id,
        f"Создана копия шаблона.\nАктивный шаблон: <b>{_esc(clone['name'])}</b>\n"
        "При необходимости отредактируйте её через /templates."
    )


def cmd_reset_sent(chat_id, data):
    data["chat_id"] = chat_id
    tmpl = _active_template(data)
    if not tmpl:
        save_data(data)
        send_msg(chat_id, "Нет активного шаблона. Нечего очищать.")
        return

    _set_template_sent_ids(data, tmpl["id"], [])
    save_data(data)
    send_msg(chat_id, f"История отправок для шаблона <b>{_esc(tmpl['name'])}</b> очищена.")

def cmd_toggle(chat_id, data):
    data["chat_id"] = chat_id
    if not _active_template(data):
        save_data(data)
        send_msg(chat_id, "Нет активного шаблона. Сначала создайте или выберите шаблон.")
        return

    data["searching"] = not data.get("searching", False)
    save_data(data)
    if data["searching"]:
        send_msg(chat_id, "<b>Автопоиск включён</b>\nНовые вакансии будут приходить по расписанию.")
    else:
        send_msg(chat_id, "<b>Автопоиск на паузе</b>\n/run — ручной запуск в любой момент.")

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
        f"Шаблон: <b>{_esc(tmpl['name']) if tmpl else 'не выбран'}</b>\n"
        f"Последняя проверка: {last_str}\n"
        f"Отправлено по текущему шаблону: {current_sent}\n"
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
         {"text": "Поиск сейчас", "callback_data": "run_now"}],
        [{"text": "Предпросмотр", "callback_data": "preview_now"},
         {"text": "Текущий шаблон", "callback_data": "menu_current"}],
    ]}
    send_msg(chat_id, text, reply_markup=kb)

def cmd_templates(chat_id, data):
    data["chat_id"] = chat_id
    save_data(data)
    tmpls = data.get("templates", [])
    if not tmpls:
        send_msg(chat_id, "Шаблонов пока нет. Создайте первый: /new")
        return

    text    = "<b>Ваши шаблоны:</b>\n\n"
    buttons = []
    for t in tmpls:
        mark = "Активный: " if t["id"] == data.get("active_template_id") else ""
        text += f"{mark}<b>{_esc(t['name'])}</b>\n"
        text += f"   {len(t.get('queries', []))} запросов · {t.get('interval', 30)} мин · {t.get('max_pages', 5)} стр. · {t.get('max_results', 50)} вакансий\n\n"
        buttons.append([
            {"text": f"{'Активный: ' if mark else ''}Выбрать: {t['name'][:18]}", "callback_data": f"tmpl_select_{t['id']}"},
            {"text": "Ред.", "callback_data": f"tmpl_edit_{t['id']}"},
            {"text": "Клон", "callback_data": f"tmpl_clone_{t['id']}"},
            {"text": "Удал.", "callback_data": f"tmpl_delete_{t['id']}"},
        ])
    buttons.append([{"text": "Новый шаблон", "callback_data": "tmpl_new"}])
    send_msg(chat_id, text, reply_markup={"inline_keyboard": buttons})

def cmd_run(chat_id, data):
    data["chat_id"] = chat_id
    save_data(data)
    tmpl = _active_template(data)
    if not tmpl:
        send_msg(chat_id, "Нет активного шаблона. Создайте через /new")
        return
    send_msg(chat_id, f"Запускаю поиск по шаблону «{_esc(tmpl['name'])}»...")
    _run_search(chat_id, data, tmpl, persist=True)


def cmd_preview(chat_id, data):
    data["chat_id"] = chat_id
    save_data(data)
    tmpl = _active_template(data)
    if not tmpl:
        send_msg(chat_id, "Нет активного шаблона. Создайте через /new")
        return
    send_msg(chat_id, f"Предпросмотр по шаблону «{_esc(tmpl['name'])}» без записи в историю...")
    _run_search(chat_id, data, tmpl, persist=False)


# ═══════════════════════════════════════════════════════════
#  ЗАПУСК ПОИСКА И ОТПРАВКА
# ═══════════════════════════════════════════════════════════

def _active_template(data):
    aid = data.get("active_template_id")
    if not aid:
        return None
    return next((t for t in data.get("templates", []) if t["id"] == aid), None)

def _run_search(chat_id, data, tmpl, persist=True):
    vacancies = fetch_vacancies(tmpl)
    sent_ids  = _template_sent_ids(data, tmpl["id"])
    sent_set  = set(sent_ids)
    new_count = 0
    sent_now = 0

    for v in vacancies:
        vid = str(v.get("id", ""))
        if persist and vid in sent_set:
            continue
        new_count += 1
        sent_now += 1
        if persist:
            sent_set.add(vid)
            sent_ids.append(vid)
        send_msg(chat_id, format_vacancy(v))
        time.sleep(0.05)

    if persist:
        data["last_check"] = time.time()
        _set_template_sent_ids(data, tmpl["id"], sent_ids)
    save_data(data)

    if new_count == 0:
        suffix = "Новых вакансий не найдено."
        if not persist:
            suffix = "По предпросмотру ничего не найдено."
        send_msg(chat_id, f"Проверка завершена: {suffix}")
    else:
        if persist:
            send_msg(chat_id, f"Отправлено <b>{sent_now}</b> новых вакансий.")
        else:
            send_msg(chat_id, f"Предпросмотр завершён: показано <b>{sent_now}</b> вакансий без записи в историю.")

    return {
        "total_found": len(vacancies),
        "sent_now": sent_now,
        "new_count": new_count,
        "persist": bool(persist),
    }


def _build_runtime_status():
    data = load_data()
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

    if cdata == "clone_active":
        data = load_data()
        cmd_clone(chat_id, data)
        return

    if cdata == "reset_sent":
        data = load_data()
        cmd_reset_sent(chat_id, data)
        return

    # ── Шаблоны ───────────────────────────────────────────
    if cdata == "tmpl_new":
        data = load_data()
        wizard_start(chat_id, data)
        return

    if cdata.startswith("tmpl_select_"):
        tmpl_id = cdata[len("tmpl_select_"):]
        data["active_template_id"] = tmpl_id
        data["searching"]          = True
        data.setdefault("sent_ids_by_template", {}).setdefault(str(tmpl_id), [])
        save_data(data)
        tmpl = next((t for t in data["templates"] if t["id"] == tmpl_id), None)
        send_msg(chat_id, f"Активный шаблон: <b>{_esc(tmpl['name'])}</b>\n"
                          "Автопоиск включён.",
                 reply_markup={"inline_keyboard": [[
                     {"text": "Редактировать", "callback_data": f"tmpl_edit_{tmpl_id}"},
                     {"text": "Поиск сейчас",  "callback_data": "run_now"},
                 ]]})
        return

    if cdata.startswith("tmpl_clone_"):
        tmpl_id = cdata[len("tmpl_clone_"):]
        tmpl = next((t for t in data["templates"] if t["id"] == tmpl_id), None)
        if not tmpl:
            send_msg(chat_id, "Шаблон для копирования не найден.")
            return

        clone = _clone_template(data, tmpl)
        save_data(data)
        send_msg(chat_id, f"Создана копия шаблона <b>{_esc(clone['name'])}</b>.")
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
        send_msg(chat_id, "Шаблон удалён.")
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
        edit_reply_markup(chat_id, msg_id, {"inline_keyboard": buttons})
        return

    if cdata == "sf_done":
        if not draft.get("search_fields"):
            draft["search_fields"] = ["name"]
        state["step"] = "experience"
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
        edit_reply_markup(chat_id, msg_id, {"inline_keyboard": buttons})
        return

    if cdata == "exp_done":
        if not draft.get("experience"):
            draft["experience"] = [ANY_EXPERIENCE]
        state["step"] = "area_scope"
        save_data(data)
        _send_area_scope_kb(chat_id)
        return

    # ── Wizard: Area scope ────────────────────────────────
    if cdata in ("scope_all", "scope_selected"):
        if cdata == "scope_all":
            draft["included_area_ids"] = []
            draft["included_area_names"] = []
            state["step"] = "exclude_areas"
            save_data(data)
            _send_exclude_area_prompt(chat_id)
        else:
            state["step"] = "include_areas"
            save_data(data)
            _send_include_area_prompt(chat_id)
        return

    # ── Wizard: Include in ────────────────────────────────
    if cdata.startswith("ii_"):
        draft["include_in"] = cdata[3:]
        state["draft"] = draft
        state["step"] = "exclude_kw"
        save_data(data)
        _send_exclude_kw_prompt(chat_id)
        return

    # ── Wizard: Exclude in ────────────────────────────────
    if cdata.startswith("ei_"):
        draft["exclude_in"] = cdata[3:]
        state["draft"]      = draft
        state["step"]       = "work_formats"
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
        state["step"] = "employment"
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
        state["step"] = "salary_mode"
        save_data(data)
        _send_salary_mode_kb(chat_id)
        return

    # ── Wizard: Salary ────────────────────────────────────
    if cdata == "sal_any":
        draft["only_with_salary"] = False
        draft["salary_min"] = 0
        state["draft"] = draft
        state["step"] = "employers"
        save_data(data)
        _send_employers_prompt(chat_id)
        return

    if cdata == "sal_only":
        draft["only_with_salary"] = True
        draft["salary_min"] = 0
        state["draft"] = draft
        state["step"] = "employers"
        save_data(data)
        _send_employers_prompt(chat_id)
        return

    if cdata == "sal_min":
        state["step"] = "salary_min"
        save_data(data)
        send_msg(chat_id, "<b>Минимальная зарплата</b>\nВведите число, например <code>120000</code>.")
        return

    # ── Wizard: Sort ──────────────────────────────────────
    if cdata.startswith("sort_"):
        draft["sort"] = cdata[5:]
        state["draft"] = draft
        state["step"]  = "period"
        save_data(data)
        _send_period_kb(chat_id)
        return

    # ── Wizard: Period ────────────────────────────────────
    if cdata.startswith("period_"):
        draft["period_days"] = int(cdata[7:])
        state["draft"] = draft
        state["step"] = "pages"
        save_data(data)
        _send_pages_kb(chat_id)
        return

    # ── Wizard: Pages ─────────────────────────────────────
    if cdata.startswith("pages_"):
        draft["max_pages"] = int(cdata[6:])
        state["draft"] = draft
        state["step"] = "max_results"
        save_data(data)
        _send_max_results_kb(chat_id)
        return

    # ── Wizard: Max results ───────────────────────────────
    if cdata.startswith("limit_"):
        draft["max_results"] = int(cdata[6:])
        state["draft"] = draft
        state["step"] = "interval"
        save_data(data)
        _send_interval_kb(chat_id)
        return

    # ── Wizard: Interval ──────────────────────────────────
    if cdata.startswith("int_"):
        draft["interval"] = int(cdata[4:])
        state["draft"]    = draft
        state["step"]     = "name"
        save_data(data)
        send_msg(chat_id,
            "<b>Название шаблона</b>\n"
            f"Текущее: <code>{_esc(draft.get('name', 'Новый шаблон'))}</code>\n\n"
            "Введите новое название или <code>ok</code> чтобы оставить текущее."
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
            f"<b>Шаблон «{_esc(tmpl['name'])}» сохранён.</b>\n"
            "Автопоиск включён.\n"
            "/run — запустить поиск прямо сейчас."
        )
        return

    if cdata == "confirm_cancel":
        if str(chat_id) in data["user_states"]:
            del data["user_states"][str(chat_id)]
        save_data(data)
        send_msg(chat_id, "Создание шаблона отменено.")
        return


# ═══════════════════════════════════════════════════════════
#  ДЕФОЛТНЫЙ ШАБЛОН (из требований пользователя)
# ═══════════════════════════════════════════════════════════

def _create_default_template():
    return _normalize_template({
        "id":                 "default01",
        "name":               "Аналитик — все страны кроме Москвы",
        "queries":            DEFAULT_QUERIES[:],
        "search_fields":      ["name", "company_name", "description"],
        "experience":         ["noExperience", "between1And3"],
        "included_area_ids":  [],
        "included_area_names": [],
        "excluded_area_ids":  [str(MOSCOW_AREA_ID)],
        "excluded_area_names": ["Москва"],
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
            text = state["draft"].get("name", "Новый шаблон")
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
            cmd_start(chat_id, data)
            wizard_start(chat_id, data)
        elif cmd == "/templates":
            cmd_templates(chat_id, data)
        elif cmd == "/current":
            cmd_current(chat_id, data)
        elif cmd == "/run":
            cmd_run(chat_id, data)
        elif cmd == "/preview":
            cmd_preview(chat_id, data)
        elif cmd == "/clone":
            cmd_clone(chat_id, data)
        elif cmd == "/reset_sent":
            cmd_reset_sent(chat_id, data)
        elif cmd == "/toggle":
            cmd_toggle(chat_id, data)
        elif cmd == "/status":
            cmd_status(chat_id, data)
        else:
            send_msg(chat_id, "Неизвестная команда. /menu — быстрое меню, /help — список команд.")
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


if FastAPI is not None:
    app = FastAPI(title="HH Vacancy Bot")

    @app.get("/")
    def api_root():
        return {
            **_build_runtime_status(),
            "message": "HH bot is alive",
            "hobby_note": "На Vercel Hobby cron ограничен. Для частого автопоиска используйте ручной /run или внешний scheduler на /api/cron.",
        }

    @app.get("/status")
    @app.get("/api/status")
    def api_status():
        return _build_runtime_status()

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
