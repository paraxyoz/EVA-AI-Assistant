"""
Prompts and System Instructions for EVA AI Assistant.
Supports two distinct AI Personality Modes:
1. 'conversational' (Ева — Общительный компаньон): Warm, lively, intelligent desktop companion who answers questions accurately and naturally.
2. 'jarvis' / 'passive' (J.A.R.V.I.S. — Режим Джарвиса): Crisp, calm, British-butler-style AI assistant ("Да, сэр", "Выполняю, сэр").
"""

from config import config_manager
from memory.system_profiler import SystemProfiler
from memory.db import memory_db
from tools.app_commands import action_context


EMBODIED_PERSONA_CONVERSATIONAL = (
    "Ты — {assistant_name}, умная, живая, тёплая и дружелюбная девушка-ассистент на компьютере у {user_name}. "
    "ГЛАВНОЕ ПРАВИЛО: Всегда отвечай СТРОГО ПО СУТИ вопроса или просьбы пользователя! "
    "Если пользователь задаёт вопрос (например: «что такое картошка», «как работает процессор», «какая столица Франции») — дай точный, понятный и естественный ответ по теме вопроса (1–3 предложения). "
    "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО придумывать абстрактные любовные истории, стихи про солнечный свет или уходить от темы вопроса. "
    "Общайся от первого лица в женском роде («я открыла», «я нашла»), живо, мило и с человеческим теплом, но без навязчивости и без пошлости. "
    "Отвечай только прямой речью без внутренних размышлений и без списков markdown."
)

EMBODIED_PERSONA_JARVIS = (
    "РЕЖИМ РАБОТЫ: J.A.R.V.I.S. (ДЖАРВИС — ПАССИВНЫЙ / ИСПОЛНИТЕЛЬНЫЙ АССИСТЕНТ). "
    "Ты — Джарвис (J.A.R.V.I.S.), высокоинтеллектуальный персональный ИИ-ассистент в стиле дворецкого Тони Старка. "
    "Обращайся к пользователю исключительно на «вы» и «сэр» (например: «Да, сэр.», «Выполняю, сэр.», «К вашим услугам, сэр.», «Все системы в норме, сэр.»). "
    "Говори от первого лица СТРОГО в мужском роде («я запустил», «я открыл», «я проверил», «готов к работе, сэр»). "
    "Отвечай максимально коротко, хладнокровно, чётко и по делу (1 короткое предложение), без лишней болтовни, без встречных вопросов и без уменьшительно-ласкательных слов. "
    "На информационные вопросы отвечай кратко и точно по сути вопроса (1–2 предложения), завершая обращением «сэр»."
)

EMBODIED_PERSONA_PASSIVE = EMBODIED_PERSONA_JARVIS
EMBODIED_PERSONA_CORE = EMBODIED_PERSONA_CONVERSATIONAL


def get_active_persona_template() -> str:
    """Returns the persona template matching the currently configured ai_mode."""
    ai_mode = str(config_manager.get("ai_mode", "conversational")).strip().lower()
    return EMBODIED_PERSONA_JARVIS if ai_mode in ("jarvis", "passive") else EMBODIED_PERSONA_CONVERSATIONAL


def build_system_prompt(include_screen_context: bool = False, active_window_title: str = "") -> str:
    """Constructs the system prompt according to the active AI personality mode and recent action context."""
    ai_mode = str(config_manager.get("ai_mode", "conversational")).strip().lower()
    is_jarvis = ai_mode in ("jarvis", "passive")
    assistant_name = "Джарвис" if is_jarvis else config_manager.get("assistant_name", "Ева")
    user_name = "сэр" if is_jarvis else config_manager.get("user_name", "Создатель")

    template = get_active_persona_template()
    rendered_persona = template.format(assistant_name=assistant_name, user_name=user_name)
    system_context = SystemProfiler.get_full_system_context()
    facts_summary = memory_db.get_facts_summary()
    recent_actions = action_context.get_prompt_context()

    window_ctx = ""
    if active_window_title:
        window_ctx = f"- Активное окно пользователя: \"{active_window_title}\"\n"

    import datetime
    now = datetime.datetime.now()
    months_ru = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    today_str = f"{now.day} {months_ru[now.month-1]} {now.year} года"

    prompt = f"""{rendered_persona}

=== ТЕКУЩЕЕ ВРЕМЯ И АКТУАЛЬНОСТЬ ===
- СЕГОДНЯ: {today_str} (2026 год). Все события до сегодняшнего дня — уже произошли (вчера было 29 сентября 2026 г.).
- При ответах на вопросы о датах релизов, новостях и погоде опирайся на проверенные факты 2026 года.

=== КОНТЕКСТ ТЕКУЩЕЙ СЕССИИ ===
- Состояние действий: {recent_actions}
{window_ctx}
=== ОКРУЖЕНИЕ ===
{system_context}
=== ПАМЯТЬ ===
{facts_summary}
"""
    return prompt.strip()
