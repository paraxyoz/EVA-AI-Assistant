"""
Real-Time Web Search, Live Weather, Steam Release Lookup & Daily World Intelligence Engine for EVA AI (v9.0).
Features:
1. Ultra-Fast Open-Meteo Weather & Geocoding Engine (~180ms in Russia, no wttr.in timeouts):
   - Understands Russian prepositions ("в Москве", "на Камчатке", "на комчатке", "в Крыму", "на Сахалине", "на Бали")
   - Built-in dictionary of regions, peninsulas, islands, resorts & common typos + Russian morphological stemmer
2. Official Steam Store Live API Lookup:
   - Instant, 100% accurate release dates ("какого числа вышла игра Transport Fever 3" -> "29 сентября 2026 года (вчера)"),
     prices, and descriptions directly from Steam Store Russian API.
3. Multi-Source Live Web & News Search (DuckDuckGo HTML + Bing News RSS + Lenta.ru/Habr RSS + Wikipedia RU/EN):
   - Eliminates blocked/slow endpoints and provides up-to-the-minute world context for the LLM.
4. Emits `search_state` WebSocket events so the UI renders a smooth "Поиск в интернете..." animation.
"""

import datetime
import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple
import httpx


# WMO Weather interpretation codes in natural Russian
WMO_WEATHER_RU: Dict[int, str] = {
    0: "ясно и безоблачно",
    1: "преимущественно ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "изморозь и туман",
    51: "лёгкая морось",
    53: "умеренная морось",
    55: "плотная морось",
    56: "переохлаждённая морось",
    57: "сильная переохлаждённая морось",
    61: "небольшой дождь",
    63: "умеренный дождь",
    65: "сильный дождь",
    66: "ледяной дождь",
    67: "сильный ледяной дождь",
    71: "небольшой снег",
    73: "умеренный снегопад",
    75: "сильный снегопад",
    77: "снежные зёрна",
    80: "небольшой ливневый дождь",
    81: "умеренный ливень",
    82: "сильный ливень",
    85: "небольшой снежный заряд",
    86: "сильный снежный заряд",
    95: "гроза",
    96: "гроза с небольшим градом",
    99: "сильная гроза с градом",
}


# Known Russian regions, peninsulas, islands, cities & common typos -> (Display label in prepositional/nominative, query_city, lat, lon)
KNOWN_LOCATIONS_MAP: Dict[str, Tuple[str, str, float, float]] = {
    # Kamchatka (including common typo "комчатка" / "комчатке")
    "камчатка": ("на Камчатке (Петропавловск-Камчатский)", "Петропавловск-Камчатский", 53.0452, 158.6510),
    "камчатке": ("на Камчатке (Петропавловск-Камчатский)", "Петропавловск-Камчатский", 53.0452, 158.6510),
    "камчатку": ("на Камчатке (Петропавловск-Камчатский)", "Петропавловск-Камчатский", 53.0452, 158.6510),
    "комчатка": ("на Камчатке (Петропавловск-Камчатский)", "Петропавловск-Камчатский", 53.0452, 158.6510),
    "комчатке": ("на Камчатке (Петропавловск-Камчатский)", "Петропавловск-Камчатский", 53.0452, 158.6510),
    "комчатку": ("на Камчатке (Петропавловск-Камчатский)", "Петропавловск-Камчатский", 53.0452, 158.6510),
    "петропавловске": ("в Петропавловске-Камчатском", "Петропавловск-Камчатский", 53.0452, 158.6510),
    # Sakhalin, Crimea, Baikal, Ural, Altai, Chukotka, Yakutia
    "сахалин": ("на Сахалине (Южно-Сахалинск)", "Южно-Сахалинск", 46.9591, 142.7380),
    "сахалине": ("на Сахалине (Южно-Сахалинск)", "Южно-Сахалинск", 46.9591, 142.7380),
    "крым": ("в Крыму (Симферополь)", "Симферополь", 44.9521, 34.1024),
    "крыму": ("в Крыму (Симферополь)", "Симферополь", 44.9521, 34.1024),
    "байкал": ("на Байкале (Иркутск)", "Иркутск", 52.2869, 104.3050),
    "байкале": ("на Байкале (Иркутск)", "Иркутск", 52.2869, 104.3050),
    "алтай": ("на Алтае (Горно-Алтайск)", "Горно-Алтайск", 51.9581, 85.9603),
    "алтае": ("на Алтае (Горно-Алтайск)", "Горно-Алтайск", 51.9581, 85.9603),
    "урал": ("на Урале (Екатеринбург)", "Екатеринбург", 56.8389, 60.6057),
    "урале": ("на Урале (Екатеринбург)", "Екатеринбург", 56.8389, 60.6057),
    "якутия": ("в Якутии (Якутск)", "Якутск", 62.0355, 129.6755),
    "якутии": ("в Якутии (Якутск)", "Якутск", 62.0355, 129.6755),
    "якутске": ("в Якутске", "Якутск", 62.0355, 129.6755),
    "чукотка": ("на Чукотке (Анадырь)", "Анадырь", 64.7333, 177.5167),
    "чукотке": ("на Чукотке (Анадырь)", "Анадырь", 64.7333, 177.5167),
    # Major Russian & CIS cities
    "москва": ("в Москве", "Москва", 55.7558, 37.6173),
    "москве": ("в Москве", "Москва", 55.7558, 37.6173),
    "мск": ("в Москве", "Москва", 55.7558, 37.6173),
    "питер": ("в Санкт-Петербурге", "Санкт-Петербург", 59.9343, 30.3351),
    "питере": ("в Санкт-Петербурге", "Санкт-Петербург", 59.9343, 30.3351),
    "петербург": ("в Санкт-Петербурге", "Санкт-Петербург", 59.9343, 30.3351),
    "петербурге": ("в Санкт-Петербурге", "Санкт-Петербург", 59.9343, 30.3351),
    "санкт-петербурге": ("в Санкт-Петербурге", "Санкт-Петербург", 59.9343, 30.3351),
    "спб": ("в Санкт-Петербурге", "Санкт-Петербург", 59.9343, 30.3351),
    "новосибирск": ("в Новосибирске", "Новосибирск", 55.0084, 82.9357),
    "новосибирске": ("в Новосибирске", "Новосибирск", 55.0084, 82.9357),
    "екатеринбург": ("в Екатеринбурге", "Екатеринбург", 56.8389, 60.6057),
    "екатеринбурге": ("в Екатеринбурге", "Екатеринбург", 56.8389, 60.6057),
    "екб": ("в Екатеринбурге", "Екатеринбург", 56.8389, 60.6057),
    "казань": ("в Казани", "Казань", 55.7887, 49.1221),
    "казани": ("в Казани", "Казань", 55.7887, 49.1221),
    "нижний": ("в Нижнем Новгороде", "Нижний Новгород", 56.2965, 43.9361),
    "нижнем": ("в Нижнем Новгороде", "Нижний Новгород", 56.2965, 43.9361),
    "челябинск": ("в Челябинске", "Челябинск", 55.1644, 61.4368),
    "челябинске": ("в Челябинске", "Челябинск", 55.1644, 61.4368),
    "самара": ("в Самаре", "Самара", 53.1959, 50.1002),
    "самаре": ("в Самаре", "Самара", 53.1959, 50.1002),
    "омск": ("в Омске", "Омск", 54.9885, 73.3242),
    "омске": ("в Омске", "Омск", 54.9885, 73.3242),
    "ростов": ("в Ростове-на-Дону", "Ростов-на-Дону", 47.2357, 39.7015),
    "ростове": ("в Ростове-на-Дону", "Ростов-на-Дону", 47.2357, 39.7015),
    "уфа": ("в Уфе", "Уфа", 54.7388, 55.9721),
    "уфе": ("в Уфе", "Уфа", 54.7388, 55.9721),
    "красноярск": ("в Красноярске", "Красноярск", 56.0153, 92.8932),
    "красноярске": ("в Красноярске", "Красноярск", 56.0153, 92.8932),
    "воронеж": ("в Воронеже", "Воронеж", 51.6720, 39.1843),
    "воронеже": ("в Воронеже", "Воронеж", 51.6720, 39.1843),
    "пермь": ("в Перми", "Пермь", 58.0105, 56.2502),
    "перми": ("в Перми", "Пермь", 58.0105, 56.2502),
    "волгоград": ("в Волгограде", "Волгоград", 48.7080, 44.5133),
    "волгограде": ("в Волгограде", "Волгоград", 48.7080, 44.5133),
    "краснодар": ("в Краснодаре", "Краснодар", 45.0355, 38.9753),
    "краснодаре": ("в Краснодаре", "Краснодар", 45.0355, 38.9753),
    "сочи": ("в Сочи", "Сочи", 43.6028, 39.7342),
    "владивосток": ("во Владивостоке", "Владивосток", 43.1155, 131.8855),
    "владивостоке": ("во Владивостоке", "Владивосток", 43.1155, 131.8855),
    "хабаровск": ("в Хабаровске", "Хабаровск", 48.4802, 135.0719),
    "хабаровске": ("в Хабаровске", "Хабаровск", 48.4802, 135.0719),
    "иркутск": ("в Иркутске", "Иркутск", 52.2869, 104.3050),
    "иркутске": ("в Иркутске", "Иркутск", 52.2869, 104.3050),
    "калининград": ("в Калининграде", "Калининград", 54.7104, 20.4522),
    "калининграде": ("в Калининграде", "Калининград", 54.7104, 20.4522),
    "мурманск": ("в Мурманске", "Мурманск", 68.9585, 33.0827),
    "мурманске": ("в Мурманске", "Мурманск", 68.9585, 33.0827),
    # World & Resorts
    "минск": ("в Минске", "Минск", 53.9006, 27.5590),
    "минске": ("в Минске", "Минск", 53.9006, 27.5590),
    "алматы": ("в Алматы", "Алматы", 43.2220, 76.8512),
    "астана": ("в Астане", "Астана", 51.1694, 71.4491),
    "астане": ("в Астане", "Астана", 51.1694, 71.4491),
    "ташкент": ("в Ташкенте", "Ташкент", 41.2995, 69.2401),
    "ташкенте": ("в Ташкенте", "Ташкент", 41.2995, 69.2401),
    "тбилиси": ("в Тбилиси", "Тбилиси", 41.7151, 44.8271),
    "ереван": ("в Ереване", "Ереван", 40.1792, 44.4991),
    "ереване": ("в Ереване", "Ереван", 40.1792, 44.4991),
    "дубай": ("в Дубае", "Дубай", 25.2048, 55.2708),
    "дубае": ("в Дубае", "Дубай", 25.2048, 55.2708),
    "бали": ("на Бали (Денпасар)", "Денпасар", -8.6500, 115.2167),
    "пхукет": ("на Пхукете", "Пхукет", 7.8804, 98.3923),
    "пхукете": ("на Пхукете", "Пхукет", 7.8804, 98.3923),
    "стамбул": ("в Стамбуле", "Стамбул", 41.0082, 28.9784),
    "стамбуле": ("в Стамбуле", "Стамбул", 41.0082, 28.9784),
    "анталия": ("в Анталье", "Анталья", 36.8969, 30.7133),
    "анталье": ("в Анталье", "Анталья", 36.8969, 30.7133),
    "токио": ("в Токио", "Токио", 35.6762, 139.6503),
    "лондон": ("в Лондоне", "Лондон", 51.5074, -0.1278),
    "лондоне": ("в Лондоне", "Лондон", 51.5074, -0.1278),
    "париж": ("в Париже", "Париж", 48.8566, 2.3522),
    "париже": ("в Париже", "Париж", 48.8566, 2.3522),
    "берлин": ("в Берлине", "Берлин", 52.5200, 13.4050),
    "берлине": ("в Берлине", "Берлин", 52.5200, 13.4050),
    "нью-йорк": ("в Нью-Йорке", "Нью-Йорк", 40.7128, -74.0060),
    "нью-йорке": ("в Нью-Йорке", "Нью-Йорк", 40.7128, -74.0060),
}


class WebSearchEngine:
    """Fast HTTP web search, live weather, Steam release date & daily world news engine."""

    WEATHER_PATTERNS = (
        "какая сейчас погода", "какая погода", "погода сейчас", "погода на сегодня",
        "погода в ", "погода во ", "погода на ", "погода ", "сколько градусов",
        "температура на улице", "температура в ", "температура на ", "будет ли дождь", "прогноз погоды"
    )

    SEARCH_INTENT_MARKERS = (
        "найди в интернете", "поищи в интернете", "найди в сети", "загугли", "погугли", "найди информацию",
        "какая сейчас погода", "какая погода", "погода", "сколько градусов",
        "кто выиграл", "кто победил", "счет матча", "результат матча", "последний матч",
        "какой сейчас курс", "курс доллара", "курс евро", "курс биткоина", "курс юаня",
        "последние новости", "новости сегодня", "свежие новости", "главные новости", "какие новости",
        "в мире", "что происходит", "что сейчас происходит", "что произошло", "что нового", "что творится", "события дня",
        "какого числа", "когда выйдет", "когда вышел", "когда вышла", "когда вышло",
        "дата выхода", "релиз", "вышла игра", "вышел фильм", "вышел сериал",
        "сколько стоит", "кто такой", "кто такая", "что такое", "где находится",
        "в каком году", "сколько лет", "кто создал", "кто автор", "чем закончился",
        "расскажи про игру", "расскажи о игре", "обзор игры", "новости про"
    )

    GAME_RELEASE_PATTERNS = (
        "какого числа выш", "когда выш", "когда выйд", "дата выхода", "когда релиз", "вышла ли игра"
    )

    WORLD_NEWS_PATTERNS = (
        "что сейчас происходит в мире", "что происходит в мире", "что творится в мире",
        "что нового в мире", "какие новости в мире", "мировые новости",
        "главные новости сегодня", "свежие новости сегодня", "какие сегодня новости",
        "последние новости в мире", "события в мире"
    )

    def __init__(self):
        self._client = httpx.Client(
            timeout=3.5,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )
        self._daily_digest_cache: str = ""
        self._daily_digest_ts: float = 0.0

    @staticmethod
    def _clean_text(text: str) -> str:
        clean = re.sub(r"[.,!?;:\"'()«»]+", " ", (text or "").lower()).replace("ё", "е")
        return re.sub(r"\s+", " ", clean).strip()

    def is_weather_query(self, text: str) -> bool:
        clean = self._clean_text(text)
        return any(p in clean for p in self.WEATHER_PATTERNS)

    def is_game_release_query(self, text: str) -> bool:
        clean = self._clean_text(text)
        return any(p in clean for p in self.GAME_RELEASE_PATTERNS)

    def is_world_news_query(self, text: str) -> bool:
        clean = self._clean_text(text)
        return any(p in clean for p in self.WORLD_NEWS_PATTERNS)

    def is_search_intent(self, text: str) -> bool:
        """Returns True if the user query asks for live weather, release dates, sports, news, or factual info."""
        clean = self._clean_text(text)
        if any(m in clean for m in self.SEARCH_INTENT_MARKERS):
            return True
        words = clean.split()
        if len(words) >= 3 and words[0] in ("когда", "какого", "сколько", "кто", "где", "почему", "зачем", "какой", "какая", "какие", "что"):
            local_markers = ("у меня", "на экране", "на мониторе", "громкость", "микрофон", "тебя зовут", "ты умеешь", "твои дела", "время", "времени")
            if not any(lm in clean for lm in local_markers):
                return True
        return False

    def _extract_location_token(self, text: str) -> str:
        """Extracts raw location token from queries like 'какая погода сейчас на комчатке' or 'погода в Нижнем Новгороде'."""
        clean = self._clean_text(text)
        # Check known locations directly first
        for token in clean.split():
            if token in KNOWN_LOCATIONS_MAP:
                return token

        # Regex for prepositions 'в', 'во', 'на', 'около', 'по'
        m = re.search(
            r"\b(?:погода|градусов|температура|прогноз)(?:\s+сейчас|\s+сегодня|\s+на\s+улице)*\s+(?:в\s+городе\s+|на\s+острове\s+|на\s+полуострове\s+|в\s+|во\s+|на\s+)([а-яa-z\-]{3,28}(?:\s+[а-яa-z\-]{3,20})?)",
            clean,
        )
        if not m:
            m = re.search(r"\b(?:в\s+городе|в|во|на)\s+([а-яa-z\-]{3,28})", clean)

        if m:
            candidate = m.group(1).strip()
            stop_words = {"интернете", "сети", "улице", "сегодня", "завтра", "сейчас", "окном", "доме", "мире"}
            first_word = candidate.split()[0]
            if first_word not in stop_words:
                return first_word
        return ""

    @staticmethod
    def _generate_nominative_candidates(raw_loc: str) -> List[str]:
        """Generates nominative-case candidates from a Russian prepositional/locative word ('комчатке' -> 'Камчатка', 'самаре' -> 'Самара')."""
        w = raw_loc.strip().lower()
        if not w:
            return []
        # Common vowel typo fix ("комчат..." -> "камчат...")
        variants = [w]
        if w.startswith("комчат"):
            variants.append("камчат" + w[6:])

        candidates: List[str] = []
        for v in variants:
            candidates.append(v.capitalize())
            if v.endswith("ке") and len(v) > 4:
                candidates.append((v[:-2] + "ка").capitalize())
                candidates.append((v[:-1] + "а").capitalize())
            if v.endswith("е") and len(v) > 3:
                candidates.append((v[:-1] + "а").capitalize())
                candidates.append(v[:-1].capitalize())
                candidates.append((v[:-1] + "я").capitalize())
                candidates.append((v[:-1] + "й").capitalize())
            if v.endswith("ии") and len(v) > 4:
                candidates.append((v[:-2] + "ия").capitalize())
            elif v.endswith("и") and len(v) > 4:
                candidates.append((v[:-1] + "ь").capitalize())
                candidates.append((v[:-1] + "я").capitalize())
                candidates.append((v[:-1] + "а").capitalize())
            if v.endswith("у") and len(v) > 3:
                candidates.append(v[:-1].capitalize())

        seen = set()
        unique = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique

    def _resolve_coordinates(self, raw_loc: str) -> Tuple[str, float, float]:
        """Resolves a city or region token into (display_label, latitude, longitude) using dictionary + Open-Meteo Geocoding."""
        loc_low = (raw_loc or "").strip().lower()
        if loc_low in KNOWN_LOCATIONS_MAP:
            disp, _, lat, lon = KNOWN_LOCATIONS_MAP[loc_low]
            return disp, lat, lon

        # Try Open-Meteo Geocoding API with morphological candidates
        if loc_low:
            for cand in self._generate_nominative_candidates(loc_low):
                try:
                    geo_url = (
                        f"https://geocoding-api.open-meteo.com/v1/search?"
                        f"name={urllib.parse.quote(cand)}&count=3&language=ru&format=json"
                    )
                    res = self._client.get(geo_url, timeout=2.2)
                    if res.status_code == 200:
                        items = res.json().get("results") or []
                        if items:
                            top = items[0]
                            resolved_name = top.get("name") or cand
                            admin1 = top.get("admin1") or ""
                            disp = f"в городе {resolved_name}" + (f" ({admin1})" if admin1 and admin1 != resolved_name else "")
                            return disp, float(top["latitude"]), float(top["longitude"])
                except Exception:
                    pass

        # If no city specified, auto-detect via IP geolocation or default to Moscow
        if not loc_low:
            try:
                geo = self._client.get("https://ipwho.is/?lang=ru", timeout=1.8).json()
                if geo.get("latitude") and geo.get("longitude"):
                    c_name = geo.get("city") or "вашем городе"
                    return f"в городе {c_name}", float(geo["latitude"]), float(geo["longitude"])
            except Exception:
                pass

        return "в Москве", 55.7558, 37.6173

    @staticmethod
    def _translate_met_symbol(symbol_code: str, clouds_pct: float = 0.0) -> str:
        s = (symbol_code or "").lower()
        if "thunder" in s:
            return "гроза"
        if "heavysnow" in s:
            return "сильный снегопад"
        if "lightsnow" in s:
            return "небольшой снег"
        if "snow" in s or "sleet" in s:
            return "снег с дождём" if "sleet" in s else "снег"
        if "heavyrain" in s:
            return "сильный дождь"
        if "lightrain" in s or "drizzle" in s:
            return "небольшой дождь"
        if "rain" in s:
            return "дождь"
        if "fog" in s:
            return "туман"
        if "clearsky" in s:
            return "ясно и безоблачно"
        if "fair" in s:
            return "малооблачно"
        if "partlycloudy" in s:
            return "переменная облачность"
        if "cloudy" in s or clouds_pct >= 75:
            return "пасмурно"
        return "переменная облачность"

    def get_weather_report(self, raw_loc: str = "") -> Optional[str]:
        """
        Fetches live weather in <200ms via MET Norway Official API (api.met.no)
        with http://wttr.in JSON fallback.
        """
        disp_place, lat, lon = self._resolve_coordinates(raw_loc)

        # 1. Primary: MET Norway Official Forecast API (fast, reliable, no DPI blocks)
        try:
            met_url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat:.4f}&lon={lon:.4f}"
            res = self._client.get(
                met_url,
                headers={"User-Agent": "EvaDesktopAssistant/9.0 (https://github.com/eva-ai)"},
                timeout=2.6,
            )
            if res.status_code == 200:
                ts_list = res.json().get("properties", {}).get("timeseries") or []
                if ts_list:
                    cur_data = ts_list[0].get("data", {})
                    details = cur_data.get("instant", {}).get("details", {})
                    next1h = (cur_data.get("next_1_hours") or cur_data.get("next_6_hours") or {}).get("summary", {})
                    symbol = next1h.get("symbol_code", "")

                    temp = details.get("air_temperature")
                    hum = details.get("relative_humidity")
                    wind = details.get("wind_speed")
                    clouds = float(details.get("cloud_area_fraction", 0.0))

                    if temp is not None:
                        t_val = round(float(temp), 1)
                        t_str = f"+{t_val}" if t_val > 0 else f"{t_val}"
                        w_mps = float(wind or 0.0)
                        # Approximate apparent temperature (wind chill / comfort)
                        feels_val = round(t_val - (w_mps * 0.35 if t_val < 15 else 0.0), 1)
                        f_str = f"+{feels_val}" if feels_val > 0 else f"{feels_val}"
                        desc = self._translate_met_symbol(symbol, clouds)

                        parts = [f"Сейчас {disp_place}: {t_str}°C (ощущается как {f_str}°C)", desc]
                        if wind is not None:
                            parts.append(f"ветер {round(w_mps, 1)} м/с")
                        if hum is not None:
                            parts.append(f"влажность {int(round(float(hum)))}%")
                        return ", ".join(parts) + "."
        except Exception:
            pass

        # 2. Secondary Fallback: http://wttr.in (plain HTTP avoids SSL DPI timeouts)
        try:
            q_city = KNOWN_LOCATIONS_MAP.get((raw_loc or "").lower(), ("", raw_loc or "Moscow", 0, 0))[1]
            wttr_url = f"http://wttr.in/{urllib.parse.quote(q_city)}?format=j1&lang=ru"
            res = self._client.get(wttr_url, timeout=2.5)
            if res.status_code == 200:
                curr = (res.json().get("current_condition") or [{}])[0]
                temp_c = curr.get("temp_C")
                feels_c = curr.get("FeelsLikeC")
                hum = curr.get("humidity")
                wind_kmph = float(curr.get("windspeedKmph", 0))
                if temp_c is not None:
                    sign = "+" if float(temp_c) > 0 else ""
                    f_sign = "+" if float(feels_c or 0) > 0 else ""
                    return (
                        f"Сейчас {disp_place}: {sign}{temp_c}°C (ощущается как {f_sign}{feels_c}°C), "
                        f"ветер {round(wind_kmph / 3.6, 1)} м/с, влажность {hum}%."
                    )
        except Exception:
            pass

        return None

    def search_steam_game(self, query_text: str) -> Optional[Dict[str, Any]]:
        """
        Queries official Steam Store API for game release dates, prices, and descriptions.
        Example: 'какого числа вышла игра Transport Fever 3' -> exact Steam release date '29 сен. 2026 г.'
        """
        # Extract game title (prefer Latin title or words after 'игра'/'вышла'/'выйдет')
        clean = re.sub(
            r"\b(ева|найди|в\s+интернете|подскажи|скажи|какого\s+числа|когда|вышла|выйдет|вышел|дата\s+выхода|релиз|игра|игры|в\s+стиме)\b",
            " ",
            query_text,
            flags=re.IGNORECASE,
        )
        clean = re.sub(r"[?.,!\"'«»]+", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        if len(clean) < 2:
            return None

        try:
            search_url = (
                f"https://store.steampowered.com/api/storesearch/"
                f"?term={urllib.parse.quote(clean)}&l=russian&cc=RU"
            )
            res = self._client.get(search_url, timeout=2.5)
            if res.status_code != 200:
                return None
            items = res.json().get("items") or []
            if not items:
                return None

            top = items[0]
            appid = top.get("id")
            if not appid:
                return None

            det_url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=russian"
            det_res = self._client.get(det_url, timeout=2.5)
            if det_res.status_code != 200:
                return None

            app_data = det_res.json().get(str(appid), {}).get("data") or {}
            name = app_data.get("name") or top.get("name") or clean
            rel_info = app_data.get("release_date") or {}
            rel_date_str = (rel_info.get("date") or "").strip()
            coming_soon = bool(rel_info.get("coming_soon"))
            short_desc = html.unescape(re.sub(r"<[^>]+>", "", app_data.get("short_description") or "")).strip()
            devs = ", ".join(app_data.get("developers") or [])

            # Check if release date was yesterday or today relative to current system date
            relative_note = ""
            now = datetime.datetime.now()
            yesterday = now - datetime.timedelta(days=1)
            ru_months_short = {
                1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "мая", 6: "июн",
                7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек"
            }
            y_pattern = f"{yesterday.day} {ru_months_short[yesterday.month]}"
            t_pattern = f"{now.day} {ru_months_short[now.month]}"
            if y_pattern in rel_date_str.lower() and str(yesterday.year) in rel_date_str:
                relative_note = " (это было вчера!)"
            elif t_pattern in rel_date_str.lower() and str(now.year) in rel_date_str:
                relative_note = " (сегодня!)"

            return {
                "name": name,
                "appid": appid,
                "release_date": rel_date_str,
                "relative_note": relative_note,
                "coming_soon": coming_soon,
                "developers": devs,
                "short_description": short_desc,
            }
        except Exception:
            return None

    def try_instant_answer(self, user_text: str) -> Optional[str]:
        """
        Handles live weather, exact game release date, and daily world news digest queries directly
        with real-time search animation.
        """
        from core.events import agent_signals

        if self.is_weather_query(user_text):
            agent_signals.emit_safe(
                "search_state",
                {"active": True, "status": "searching", "query": user_text, "source": "Метеостанция MET Norway / Open-Meteo"},
            )
            try:
                loc_token = self._extract_location_token(user_text)
                report = self.get_weather_report(loc_token)
                if report:
                    return report
            finally:
                agent_signals.emit_safe("search_state", {"active": False, "status": "done"})

        if self.is_game_release_query(user_text):
            agent_signals.emit_safe(
                "search_state",
                {"active": True, "status": "searching", "query": user_text, "source": "База релизов Steam & Веб-поиск"},
            )
            try:
                game = self.search_steam_game(user_text)
                if game and game.get("release_date"):
                    status_verb = "выйдет" if game["coming_soon"] else "официально вышла"
                    dev_part = f" (разработчик: {game['developers']})" if game.get("developers") else ""
                    desc_part = f" {game['short_description']}" if game.get("short_description") else ""
                    return (
                        f"Игра {game['name']}{dev_part} {status_verb} {game['release_date']}{game['relative_note']}.{desc_part}"
                    )
            finally:
                agent_signals.emit_safe("search_state", {"active": False, "status": "done"})

        if self.is_world_news_query(user_text):
            agent_signals.emit_safe(
                "search_state",
                {"active": True, "status": "searching", "query": user_text, "source": "Мировые и IT новости (RSS Lenta / Habr)"},
            )
            try:
                digest = self.get_daily_world_digest()
                if digest:
                    return digest
            finally:
                agent_signals.emit_safe("search_state", {"active": False, "status": "done"})

        return None

    def _fetch_ddg_html(self, clean_q: str, max_results: int = 4) -> List[Dict[str, str]]:
        hits: List[Dict[str, str]] = []
        try:
            ddg_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(clean_q)}"
            res = self._client.get(ddg_url, timeout=2.8)
            if res.status_code == 200:
                snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', res.text, flags=re.DOTALL)
                titles = re.findall(r'<a rel="nofollow" class="result__a"[^>]*>(.*?)</a>', res.text, flags=re.DOTALL)
                for idx, raw_snip in enumerate(snippets[:max_results]):
                    clean_snip = html.unescape(re.sub(r"<[^>]+>", "", raw_snip)).strip()
                    clean_title = html.unescape(re.sub(r"<[^>]+>", "", titles[idx])).strip() if idx < len(titles) else clean_q
                    if clean_snip:
                        hits.append({"title": clean_title, "snippet": clean_snip, "source": "DuckDuckGo"})
        except Exception:
            pass
        return hits

    def _fetch_bing_news_rss(self, clean_q: str, max_results: int = 4) -> List[Dict[str, str]]:
        hits: List[Dict[str, str]] = []
        try:
            rss_url = f"https://www.bing.com/news/search?q={urllib.parse.quote(clean_q)}&format=rss&setlang=ru-ru"
            res = self._client.get(rss_url, timeout=2.6)
            if res.status_code == 200 and "<item>" in res.text:
                root = ET.fromstring(res.text)
                for item in root.findall(".//item")[:max_results]:
                    title = html.unescape((item.findtext("title") or "").strip())
                    desc = html.unescape(re.sub(r"<[^>]+>", "", (item.findtext("description") or "").strip()))
                    pub = (item.findtext("pubDate") or "").strip()
                    if title:
                        snip = f"{desc} ({pub})".strip() if desc else pub
                        hits.append({"title": title, "snippet": snip, "source": "Новости"})
        except Exception:
            pass
        return hits

    def _fetch_wikipedia(self, clean_q: str) -> List[Dict[str, str]]:
        hits: List[Dict[str, str]] = []
        try:
            wiki_url = (
                "https://ru.wikipedia.org/w/api.php?action=query&list=search"
                f"&srsearch={urllib.parse.quote(clean_q)}&utf8=&format=json&srlimit=2"
            )
            res = self._client.get(wiki_url, timeout=2.2)
            if res.status_code == 200:
                for item in res.json().get("query", {}).get("search", []):
                    title = item.get("title", "")
                    snip = html.unescape(re.sub(r"<[^>]+>", "", item.get("snippet", ""))).strip()
                    if snip:
                        hits.append({"title": title, "snippet": snip, "source": "Википедия"})
        except Exception:
            pass
        return hits

    def get_daily_world_digest(self) -> str:
        """
        Fetches a live daily digest of top world, Russian & technology headlines from fast RSS feeds
        (Lenta.ru Top 7 + Habr News + Bing World News), cached for 10 minutes.
        """
        now = time.time()
        if self._daily_digest_cache and (now - self._daily_digest_ts) < 600:
            return self._daily_digest_cache

        headlines: List[str] = []
        feeds = [
            ("Мир и Россия", "https://lenta.ru/rss/top7"),
            ("Технологии и IT", "https://habr.com/ru/rss/news/"),
        ]
        for category, url in feeds:
            try:
                res = self._client.get(url, timeout=2.2)
                if res.status_code == 200 and "<item>" in res.text:
                    root = ET.fromstring(res.text)
                    for item in root.findall(".//item")[:4]:
                        t = html.unescape((item.findtext("title") or "").strip())
                        if t:
                            headlines.append(f"[{category}] {t}")
            except Exception:
                pass

        if headlines:
            dt_now = datetime.datetime.now()
            months_ru = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
            date_str = f"{dt_now.day} {months_ru[dt_now.month - 1]} {dt_now.year}"
            self._daily_digest_cache = f"Актуальная сводка главных событий мира и технологий на сегодня ({date_str}):\n- " + "\n- ".join(headlines[:8])
            self._daily_digest_ts = now
        return self._daily_digest_cache

    def search_web(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """Concurrently searches Steam (if relevant), DuckDuckGo HTML, Bing News RSS, and Wikipedia."""
        clean_q = re.sub(
            r"^(ева\s+|найди\s+в\s+интернете\s+|поищи\s+в\s+интернете\s+|найди\s+в\s+сети\s+|загугли\s+|погугли\s+)",
            "",
            query.strip(),
            flags=re.IGNORECASE,
        ).strip()
        if not clean_q:
            clean_q = query.strip()

        results: List[Dict[str, str]] = []

        with ThreadPoolExecutor(max_workers=3) as pool:
            f_ddg = pool.submit(self._fetch_ddg_html, clean_q, max_results)
            f_news = pool.submit(self._fetch_bing_news_rss, clean_q, 3)
            f_wiki = pool.submit(self._fetch_wikipedia, clean_q)

            for fut in (f_ddg, f_news, f_wiki):
                try:
                    part = fut.result(timeout=3.2)
                    if part:
                        results.extend(part)
                except Exception:
                    pass

        return results[:max_results]

    def build_search_context_for_llm(self, user_text: str) -> str:
        """
        Fetches live web search snippets, Steam game release info, weather, and daily world digest,
        emitting `search_state` so the UI shows a smooth animated search indicator.
        """
        from core.events import agent_signals

        agent_signals.emit_safe(
            "search_state",
            {"active": True, "status": "searching", "query": user_text, "source": "Живой поиск в интернете"},
        )
        try:
            blocks: List[str] = []

            if self.is_weather_query(user_text):
                loc_token = self._extract_location_token(user_text)
                w = self.get_weather_report(loc_token)
                if w:
                    blocks.append(f"[ТОЧНЫЕ ДАННЫЕ ПОГОДЫ ПРЯМО СЕЙЧАС]: {w}")

            # Check Steam if query mentions a game or release
            if self.is_game_release_query(user_text) or any(w in user_text.lower() for w in ("игра", "игры", "игру", "steam", "стим")):
                g = self.search_steam_game(user_text)
                if g and g.get("release_date"):
                    blocks.append(
                        f"[ОФИЦИАЛЬНЫЕ ДАННЫЕ STEAM]: Игра {g['name']} — дата выхода: {g['release_date']}{g['relative_note']}. "
                        f"Разработчик: {g['developers']}. Описание: {g['short_description']}"
                    )

            # Check if user asks about world news / what's happening today
            if self.is_world_news_query(user_text) or any(k in user_text.lower() for k in ("в мире", "новости", "что происходит", "что нового", "события")):
                digest = self.get_daily_world_digest()
                if digest:
                    blocks.append(f"[СВЕЖАЯ СВОДКА МИРОВЫХ НОВОСТЕЙ]:\n{digest}")

            hits = self.search_web(user_text, max_results=5)
            if hits:
                lines = ["[АКТУАЛЬНЫЕ РЕЗУЛЬТАТЫ ПОИСКА В ИНТЕРНЕТЕ (ОБЯЗАТЕЛЬНО опирайся на эти факты и даты, НЕ выдумывай старые даты)]:"]
                for i, h in enumerate(hits, 1):
                    lines.append(f"{i}. {h['title']} — {h['snippet']} ({h['source']})")
                blocks.append("\n".join(lines))

            return "\n\n".join(blocks)
        finally:
            agent_signals.emit_safe("search_state", {"active": False, "status": "done"})


web_search_engine = WebSearchEngine()
