#!/usr/bin/env python3
"""
HH.ru Smart Vacancy Bot v2
===========================
Полноценный Telegram-бот для поиска вакансий на hh.ru.
Настройка поиска прямо через Telegram — без редактирования кода.

Команды:
  /start     — приветствие и помощь
  /new       — создать новый поисковый шаблон (wizard)
  /templates — список шаблонов, выбор/редактирование/удаление
  /run       — запустить поиск прямо сейчас (не ждать таймер)
  /toggle    — включить/выключить автопоиск
  /status    — текущий статус и статистика

Запуск: python3 hh_vacancy_bot.py
"""

import requests
import json
import time
import uuid
import re
from datetime import datetime

# ═══════════════════════════════════════════════════════════
#  КОНФИГ
# ═══════════════════════════════════════════════════════════

BOT_TOKEN   = "8704568628:AAFse14Tq9yE0c26_BZi3WuE31LjnfMUGqQ"
DATA_FILE   = "bot_data.json"
AREAS_CACHE = "areas_cache.json"

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
HH_API = "https://api.hh.ru"

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

def load_data():
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
            "last_check":         0,
            "user_states":        {},
        }
    return _normalize_data(data)

def save_data(data):
    data["sent_ids"] = list(data.get("sent_ids", []))[-10000:]
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
    tmpl["exclude_in"] = tmpl.get("exclude_in", "both")
    tmpl["sort"] = tmpl.get("sort", "publication_time")
    tmpl["interval"] = int(tmpl.get("interval", 30) or 30)
    tmpl["max_pages"] = int(tmpl.get("max_pages", 5) or 5)
    tmpl["name"] = (tmpl.get("name") or "Новый шаблон")[:50]
    tmpl["id"] = str(tmpl.get("id") or str(uuid.uuid4())[:8])

    return tmpl


def _normalize_data(data):
    normalized = {
        "chat_id":            data.get("chat_id"),
        "templates":          [_normalize_template(t) for t in data.get("templates", [])],
        "active_template_id": data.get("active_template_id"),
        "searching":          bool(data.get("searching", False)),
        "sent_ids":           list(data.get("sent_ids", [])),
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


# ═══════════════════════════════════════════════════════════
#  TELEGRAM API
# ═══════════════════════════════════════════════════════════

def tg_call(method, **kwargs):
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
    try:
        r = requests.post(f"{TG_API}/getUpdates",
                          json={"offset": offset, "timeout": 3, "limit": 20},
                          timeout=10)
        return r.json().get("result", [])
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════
#  HH.RU AREAS
# ═══════════════════════════════════════════════════════════

_area_tree   = None
_russia_ids  = None
_area_by_id  = None
_area_by_name = None
_area_children_cache = {}

def get_area_tree():
    global _area_tree
    if _area_tree is not None:
        return _area_tree
    try:
        with open(AREAS_CACHE, "r", encoding="utf-8") as f:
            _area_tree = json.load(f)
            return _area_tree
    except Exception:
        pass
    try:
        r = requests.get(f"{HH_API}/areas", timeout=20)
        _area_tree = r.json()
        with open(AREAS_CACHE, "w", encoding="utf-8") as f:
            json.dump(_area_tree, f, ensure_ascii=False)
        return _area_tree
    except Exception as e:
        print(f"❌ Ошибка загрузки дерева регионов: {e}")
        return []

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

def get_russia_ids():
    global _russia_ids
    if _russia_ids is not None:
        return _russia_ids
    ids = set()
    try:
        r = requests.get(f"{HH_API}/areas/{RUSSIA_AREA_ID}", timeout=20)
        _collect_ids(r.json(), ids)
    except Exception as e:
        print(f"❌ Ошибка загрузки регионов России: {e}")
    ids.add(str(RUSSIA_AREA_ID))
    _russia_ids = ids
    return _russia_ids


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

def fetch_vacancies(template):
    template = _normalize_template(template)

    included_area_ids = [str(x) for x in template.get("included_area_ids", [])]
    excluded_area_ids = [str(x) for x in template.get("excluded_area_ids", [])]
    excluded_area_ids = excluded_area_ids or []

    included_area_set = expand_area_ids(included_area_ids)
    excluded_area_set = expand_area_ids(excluded_area_ids)

    excl_kw = [k.lower() for k in template.get("exclude_keywords", [])]
    excl_in = template.get("exclude_in", "both")
    sort_by = template.get("sort", "publication_time")
    queries = template.get("queries", DEFAULT_QUERIES)
    max_pages = int(template.get("max_pages", 5) or 5)
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
                    "period":          1,
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

                    if excl_kw:
                        title = (v.get("name") or "").lower()
                        snippet = v.get("snippet") or {}
                        req = (snippet.get("requirement") or "").lower()
                        resp = (snippet.get("responsibility") or "").lower()
                        employer = (v.get("employer", {}).get("name") or "").lower()
                        desc_txt = f"{req} {resp} {employer}"

                        blocked = False
                        for kw in excl_kw:
                            hit_title = excl_in in ("title", "both") and kw in title
                            hit_desc = excl_in in ("description", "both") and kw in desc_txt
                            if hit_title or hit_desc:
                                blocked = True
                                break
                        if blocked:
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

    return _sort_vacancies(final, sort_by, queries)


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
    name     = v.get("name") or "—"
    employer = (v.get("employer") or {}).get("name") or "—"
    area     = (v.get("area") or {}).get("name") or "—"
    url      = v.get("alternate_url") or ""
    exp      = (v.get("experience") or {}).get("name") or "—"
    schedule = (v.get("schedule") or {}).get("name") or ""

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
    req  = (snippet.get("requirement") or "")[:200]
    req  = req.replace("<highlighttext>", "<b>").replace("</highlighttext>", "</b>")

    lines = [
        f"<b>{name}</b>",
        f"Компания: {employer}",
        f"Локация: {area}",
        f"Опыт: {exp}",
        f"Зарплата: {sal}",
    ]
    if schedule:
        lines.append(f"Формат: {schedule}")
    if req:
        lines.append(f"\n<i>{req}</i>")
    if url:
        lines.append(f"\n<a href='{url}'>Открыть вакансию на hh.ru</a>")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  WIZARD — МАСТЕР СОЗДАНИЯ ШАБЛОНА
# ═══════════════════════════════════════════════════════════

def wizard_start(chat_id, data, template_id=None):
    """Запускает мастер создания или редактирования шаблона."""
    if template_id:
        tmpl  = next((t for t in data["templates"] if t["id"] == template_id), None)
        draft = _normalize_template(tmpl) if tmpl else _new_draft()
        mode  = "edit"
    else:
        draft = _new_draft()
        mode  = "create"

    data["user_states"][str(chat_id)] = {
        "step":        "queries",
        "draft":       draft,
        "mode":        mode,
        "template_id": template_id,
    }
    save_data(data)

    send_msg(
        chat_id,
        "<b>Мастер настройки поиска</b>\n\n"
        "<b>Запросы</b>\n"
        "Введите названия вакансий через запятую.\n"
        "Или напишите <code>default</code> для полного набора аналитических должностей и синонимов.\n\n"
        "Пример: <code>data analyst, product analyst, business analyst</code>"
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
        "exclude_in":       "both",
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
        if lo in ("нет", "no", "none", "-", "skip"):
            draft["excluded_area_ids"] = []
            draft["excluded_area_names"] = []
        else:
            names = [n.strip() for n in txt.split(",") if n.strip()]
            area_ids, resolved_names, not_found = _resolve_area_names(names)
            draft["excluded_area_ids"] = area_ids
            draft["excluded_area_names"] = resolved_names
            if not_found:
                send_msg(chat_id, f"Не найдены регионы: <b>{', '.join(not_found)}</b>\nПродолжаю с найденными.")
        state["step"] = "exclude_kw"
        save_data(data)
        _send_exclude_kw_prompt(chat_id)
        return True

    if step == "exclude_kw":
        lo = txt.lower()
        if lo == "default":
            draft["exclude_keywords"] = DEFAULT_EXCLUDE_KEYWORDS[:]
        elif lo in ("нет", "no", "none", "-"):
            draft["exclude_keywords"] = []
        else:
            draft["exclude_keywords"] = [k.strip().lower() for k in txt.split(",") if k.strip()]
        state["step"] = "exclude_in"
        save_data(data)
        _send_exclude_in_kb(chat_id)
        return True

    if step == "name":
        if txt.lower() not in ("ok", "ок", "ок"):
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
        mark = "Выбрано: " if code in selected else "Добавить: "
        buttons.append([{"text": mark + label, "callback_data": f"sf_{code}"}])
    buttons.append([{"text": "Далее", "callback_data": "sf_done"}])
    send_msg(chat_id, "<b>Где искать совпадения</b>\nВыберите одно или несколько полей:", reply_markup={"inline_keyboard": buttons})

def _send_experience_kb(chat_id, selected):
    buttons = []
    for code, label in EXPERIENCE_OPTIONS.items():
        mark = "Выбрано: " if code in selected else "Добавить: "
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

def _send_sort_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": label, "callback_data": f"sort_{code}"}]
        for code, label in SORT_OPTIONS.items()
    ]}
    send_msg(chat_id, "<b>Сортировка</b>", reply_markup=kb)

def _send_pages_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": label, "callback_data": f"pages_{pages}"}]
        for pages, label in MAX_PAGES_OPTIONS.items()
    ]}
    send_msg(chat_id, "<b>Глубина поиска</b>\nСколько страниц просматривать для каждого запроса:", reply_markup=kb)

def _send_interval_kb(chat_id):
    kb = {"inline_keyboard": [
        [{"text": label, "callback_data": f"int_{mins}"}]
        for mins, label in INTERVAL_OPTIONS.items()
    ]}
    send_msg(chat_id, "<b>Интервал автопроверки</b>", reply_markup=kb)

def _send_confirm(chat_id, draft):
    exp_names = [EXPERIENCE_OPTIONS.get(e, e) for e in draft.get("experience", [])]
    search_fields = [SEARCH_FIELD_OPTIONS.get(f, f) for f in draft.get("search_fields", [])]
    include_names = draft.get("included_area_names", [])
    exclude_names = draft.get("excluded_area_names", [])
    kws = draft.get("exclude_keywords", [])
    kw_preview = ", ".join(kws[:6]) + (f" ... (+{len(kws)-6})" if len(kws) > 6 else "")
    excl_where = {"title": "названии", "description": "описании", "both": "везде"}.get(
        draft.get("exclude_in", "both"), "везде"
    )
    qs = draft.get("queries", [])

    if include_names:
        include_text = ", ".join(include_names)
    else:
        include_text = "Все страны и города"

    if exclude_names:
        exclude_text = ", ".join(exclude_names)
    else:
        exclude_text = "Без исключений"

    text = (
        f"<b>Шаблон: {draft.get('name', '—')}</b>\n\n"
        f"Запросов: <b>{len(qs)}</b>\n"
        f"   <i>{', '.join(qs[:4])}{'...' if len(qs) > 4 else ''}</i>\n\n"
        f"Поля поиска: {', '.join(search_fields) or '—'}\n"
        f"Опыт: {', '.join(exp_names) or '—'}\n"
        f"Искать только в: {include_text}\n"
        f"Исключить регионы: {exclude_text}\n"
        f"Слова-фильтры ({len(kws)} шт.) в {excl_where}:\n"
        f"   <i>{kw_preview or 'нет'}</i>\n"
        f"Сортировка: {SORT_OPTIONS.get(draft.get('sort',''), '—')}\n"
        f"Страниц на запрос: {draft.get('max_pages', 5)}\n"
        f"Интервал: {draft.get('interval', 30)} мин\n"
    )
    kb = {"inline_keyboard": [[
        {"text": "Сохранить", "callback_data": "confirm_save"},
        {"text": "Отмена",   "callback_data": "confirm_cancel"},
    ]]}
    send_msg(chat_id, text, reply_markup=kb)


# ═══════════════════════════════════════════════════════════
#  КОМАНДЫ БОТА
# ═══════════════════════════════════════════════════════════

def cmd_start(chat_id, data):
    data["chat_id"] = chat_id
    save_data(data)
    send_msg(chat_id,
        "<b>HH.ru Vacancy Bot</b>\n\n"
        "Отслеживаю вакансии на hh.ru и присылаю новые по вашим критериям.\n\n"
        "<b>Команды:</b>\n"
        "/new       — создать поисковый шаблон\n"
        "/templates — шаблоны (выбор/редактирование)\n"
        "/run       — запустить поиск прямо сейчас\n"
        "/toggle    — включить/выключить автопоиск\n"
        "/status    — статус и статистика\n"
        "/help      — подробная справка"
    )

def cmd_help(chat_id):
    send_msg(chat_id,
        "<b>Как пользоваться</b>\n\n"
        "1. <b>/new</b> — настройте поиск пошагово через меню\n"
        "   • Укажите должности, поля поиска, опыт, географию, фильтры, страницы и интервал\n"
        "   • Шаблон сохранится автоматически\n\n"
        "2. <b>/run</b> — немедленная проверка без ожидания таймера\n\n"
        "3. <b>/toggle</b> — пауза или возобновление автопоиска\n\n"
        "4. <b>/templates</b> — список шаблонов:\n"
        "   • Выбрать активный\n"
        "   • Редактировать (пройти wizard заново)\n"
        "   • Удалить\n\n"
        "5. Каждая вакансия содержит ссылку на hh.ru\n\n"
        "<b>Фильтры:</b>\n"
        "• География: любые страны, только выбранные страны/города, исключение стран и отдельных городов\n"
        "• Опыт: любой, без опыта, 1-3, 3-6, 6+ лет; можно выбрать несколько\n"
        "• Слова: фильтрация в названии, описании или везде\n"
        "• Сортировка: по дате, совпадению, названию, зарплате\n"
        "• Страницы: настройка глубины поиска по каждому запросу"
    )

def cmd_toggle(chat_id, data):
    data["chat_id"]   = chat_id
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

    text = (
        f"{icon} <b>Статус: {st_text}</b>\n\n"
        f"Шаблон: <b>{tmpl['name'] if tmpl else 'не выбран'}</b>\n"
        f"Последняя проверка: {last_str}\n"
        f"Отправлено всего: {len(data.get('sent_ids', []))} вакансий\n"
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
        text += f"{mark}<b>{t['name']}</b>\n"
        text += f"   {len(t.get('queries', []))} запросов · {t.get('interval', 30)} мин · {t.get('max_pages', 5)} стр.\n\n"
        buttons.append([
            {"text": f"{'Активный: ' if mark else ''}Выбрать: {t['name'][:18]}", "callback_data": f"tmpl_select_{t['id']}"},
            {"text": "Ред.", "callback_data": f"tmpl_edit_{t['id']}"},
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
    send_msg(chat_id, f"Запускаю поиск по шаблону «{tmpl['name']}»...")
    _run_search(chat_id, data, tmpl)


# ═══════════════════════════════════════════════════════════
#  ЗАПУСК ПОИСКА И ОТПРАВКА
# ═══════════════════════════════════════════════════════════

def _active_template(data):
    aid = data.get("active_template_id")
    if not aid:
        return None
    return next((t for t in data.get("templates", []) if t["id"] == aid), None)

def _run_search(chat_id, data, tmpl):
    vacancies = fetch_vacancies(tmpl)
    sent_set  = set(data.get("sent_ids", []))
    new_count = 0

    for v in vacancies:
        vid = str(v.get("id", ""))
        if vid in sent_set:
            continue
        sent_set.add(vid)
        new_count += 1
        send_msg(chat_id, format_vacancy(v))
        time.sleep(0.05)

    data["sent_ids"]   = list(sent_set)
    data["last_check"] = time.time()
    save_data(data)

    if new_count == 0:
        send_msg(chat_id, "Проверка завершена: новых вакансий не найдено.")
    else:
        send_msg(chat_id, f"Отправлено <b>{new_count}</b> новых вакансий.")


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

    # ── Шаблоны ───────────────────────────────────────────
    if cdata == "tmpl_new":
        data = load_data()
        wizard_start(chat_id, data)
        return

    if cdata.startswith("tmpl_select_"):
        tmpl_id = cdata[len("tmpl_select_"):]
        data["active_template_id"] = tmpl_id
        data["searching"]          = True
        save_data(data)
        tmpl = next((t for t in data["templates"] if t["id"] == tmpl_id), None)
        send_msg(chat_id, f"Активный шаблон: <b>{tmpl['name']}</b>\n"
                          "Автопоиск включён.",
                 reply_markup={"inline_keyboard": [[
                     {"text": "Редактировать", "callback_data": f"tmpl_edit_{tmpl_id}"},
                     {"text": "Поиск сейчас",  "callback_data": "run_now"},
                 ]]})
        return

    if cdata.startswith("tmpl_edit_"):
        tmpl_id = cdata[len("tmpl_edit_"):]
        data    = load_data()
        wizard_start(chat_id, data, template_id=tmpl_id)
        return

    if cdata.startswith("tmpl_delete_"):
        tmpl_id = cdata[len("tmpl_delete_"):]
        data["templates"] = [t for t in data["templates"] if t["id"] != tmpl_id]
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
            mark = "Выбрано: " if field_code in draft["search_fields"] else "Добавить: "
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
            mark = "Выбрано: " if c in draft["experience"] else "Добавить: "
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

    # ── Wizard: Exclude in ────────────────────────────────
    if cdata.startswith("ei_"):
        draft["exclude_in"] = cdata[3:]
        state["draft"]      = draft
        state["step"]       = "sort"
        save_data(data)
        _send_sort_kb(chat_id)
        return

    # ── Wizard: Sort ──────────────────────────────────────
    if cdata.startswith("sort_"):
        draft["sort"] = cdata[5:]
        state["draft"] = draft
        state["step"]  = "pages"
        save_data(data)
        _send_pages_kb(chat_id)
        return

    # ── Wizard: Pages ─────────────────────────────────────
    if cdata.startswith("pages_"):
        draft["max_pages"] = int(cdata[6:])
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
            f"Текущее: <code>{draft.get('name', 'Новый шаблон')}</code>\n\n"
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
        if str(chat_id) in data["user_states"]:
            del data["user_states"][str(chat_id)]
        save_data(data)
        send_msg(chat_id,
            f"<b>Шаблон «{tmpl['name']}» сохранён.</b>\n"
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
        "exclude_keywords":   DEFAULT_EXCLUDE_KEYWORDS[:],
        "exclude_in":         "both",
        "sort":               "match_desc",
        "interval":           30,
        "max_pages":          5,
    })


# ═══════════════════════════════════════════════════════════
#  ГЛАВНЫЙ ЦИКЛ
# ═══════════════════════════════════════════════════════════

def main():
    print("🤖 HH.ru Vacancy Bot запускается...")
    data   = load_data()
    offset = 0

    # Создаём дефолтный шаблон при первом запуске
    if not data.get("templates"):
        tmpl = _create_default_template()
        data["templates"]          = [tmpl]
        data["active_template_id"] = tmpl["id"]
        save_data(data)
        print("✅ Создан дефолтный шаблон поиска")

    print("📡 Загружаю дерево регионов HH...")
    _index_areas()
    print("✅ Готов. Отправьте /start боту в Telegram.")

    while True:
        try:
            updates = get_updates(offset)
        except Exception as e:
            print(f"❌ Ошибка получения обновлений: {e}")
            time.sleep(5)
            continue

        for upd in updates:
            offset = upd["update_id"] + 1
            data   = load_data()

            # ── Callback query (кнопки) ──────────────────
            if "callback_query" in upd:
                try:
                    handle_callback(upd["callback_query"], data)
                except Exception as e:
                    print(f"❌ Ошибка callback: {e}")
                continue

            # ── Текстовые сообщения ──────────────────────
            msg = upd.get("message", {})
            if not msg:
                continue

            chat_id = msg["chat"]["id"]
            text    = (msg.get("text") or "").strip()
            if not text:
                continue

            # Сохраняем chat_id при любом сообщении
            if data.get("chat_id") != chat_id:
                data["chat_id"] = chat_id
                save_data(data)

            # Wizard перехватывает текстовый ввод
            state = data["user_states"].get(str(chat_id))
            if state and not text.startswith("/"):
                # Для шага "name" поддерживаем "ok"
                if state["step"] == "name" and text.lower() in ("ok", "ок"):
                    text = state["draft"].get("name", "Новый шаблон")
                try:
                    wizard_handle_text(chat_id, text, data)
                except Exception as e:
                    print(f"❌ Ошибка wizard: {e}")
                continue

            # Команды
            cmd = text.split()[0].split("@")[0].lower()
            try:
                if cmd == "/start":
                    cmd_start(chat_id, data)
                elif cmd == "/help":
                    cmd_help(chat_id)
                elif cmd == "/new":
                    cmd_start(chat_id, data)   # регистрируем chat_id
                    wizard_start(chat_id, data)
                elif cmd == "/templates":
                    cmd_templates(chat_id, data)
                elif cmd == "/run":
                    cmd_run(chat_id, data)
                elif cmd == "/toggle":
                    cmd_toggle(chat_id, data)
                elif cmd == "/status":
                    cmd_status(chat_id, data)
                else:
                    send_msg(chat_id,
                        "Неизвестная команда. /help — список команд.")
            except Exception as e:
                print(f"❌ Ошибка команды {cmd}: {e}")

        # ── Плановый автопоиск ───────────────────────────
        data  = load_data()
        chat_id = data.get("chat_id")

        if data.get("searching") and data.get("active_template_id") and chat_id:
            tmpl = _active_template(data)
            if tmpl:
                interval  = tmpl.get("interval", 30) * 60
                last_chk  = data.get("last_check", 0)
                if time.time() - last_chk >= interval:
                    print(f"🔍 Плановый поиск: {tmpl['name']}")
                    try:
                        _run_search(chat_id, data, tmpl)
                    except Exception as e:
                        print(f"❌ Ошибка планового поиска: {e}")
                        data["last_check"] = time.time()
                        save_data(data)

        time.sleep(1)


if __name__ == "__main__":
    main()
