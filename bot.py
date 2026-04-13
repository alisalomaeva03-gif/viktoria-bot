#!/usr/bin/env python3
"""
Бот Фунтик — умный ассистент Виктории
Задачи / Идеи / Заметки + управление + ежедневный дайджест 9:00 Самара
"""

import os
import re
import json
import logging
import warnings
warnings.filterwarnings('ignore')
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

BOT_TOKEN = os.environ.get('BOT_TOKEN', '8671820769:AAE-Z9aeHvrSyyPNM6ZEAd0OvWzm3gMziuE')
SHEET_URL = "https://docs.google.com/spreadsheets/d/10JPsb1p9z9TrhTQ5IgdIek_mMlxyoeRFE-OTLMZhhus/edit"
SAMARA_TZ = ZoneInfo("Europe/Samara")

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# ─── Google Sheets ────────────────────────────────────────────────────────────
def get_sheet():
    from google.oauth2.service_account import Credentials
    import gspread
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if creds_json:
        creds = Credentials.from_service_account_info(
            json.loads(creds_json),
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
    else:
        creds = Credentials.from_service_account_file(
            os.path.expanduser('~/telegram_bot/google_credentials.json'),
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
    return gspread.authorize(creds).open_by_url(SHEET_URL)


def save_to_sheet(sheet_name, row):
    try:
        get_sheet().worksheet(sheet_name).append_row(row)
        return True
    except Exception as e:
        logger.error(f"Sheet error [{sheet_name}]: {e}")
        return False


def now_samara():
    return datetime.now(SAMARA_TZ).strftime('%d.%m.%Y %H:%M')


# ─── Слова-триггеры ───────────────────────────────────────────────────────────

# Ключевые слова для распознавания запросов — проверяются по отдельности,
# чтобы работало при любом порядке слов: «какие задачи», «задачи какие», «на сегодня задачи» и т.д.

# Слова-сигналы «покажи/что есть»
QUERY_SIGNAL = [
    'какие', 'покажи', 'список', 'все', 'мои', 'что там', 'что за',
    'что сейчас', 'сегодня', 'на сегодня', 'текущие', 'активные',
    'есть ли', 'что в работе', 'что надо', 'что нужно',
]
# Ключевые слова тематики
TASK_KEYWORDS  = ['задач', 'задачи', 'задача', 'задание', 'задания']
IDEA_KEYWORDS  = ['иде', 'идея', 'идеи']
NOTE_KEYWORDS  = ['заметк', 'заметки', 'заметка']

DELETE_TASK_WORDS  = ['удали задачу',  'удалить задачу',  'убери задачу',
                      'удали задание', 'удалить задание', 'убери задание']
DELETE_IDEA_WORDS  = ['удали идею',    'удалить идею',    'убери идею']
DELETE_NOTE_WORDS  = ['удали заметку', 'удалить заметку', 'убери заметку']


def _has_query_signal(t: str) -> bool:
    """Есть ли в тексте слово-сигнал запроса списка."""
    return any(w in t for w in QUERY_SIGNAL)

def _has_keyword(t: str, keywords: list) -> bool:
    """Есть ли хотя бы одно ключевое слово темы."""
    return any(w in t for w in keywords)

TASK_WORDS = [
    'надо', 'нужно', 'сделать', 'позвонить', 'написать', 'отправить',
    'встретиться', 'купить', 'оплатить', 'подготовить', 'договориться',
    'не забыть', 'напомни', 'поставить', 'узнать', 'проверить',
    'запланировать', 'созвониться', 'отвезти', 'забрать', 'сдать',
    'починить', 'разобраться', 'решить', 'завершить', 'доделать',
    'задача', 'поставь задачу',
]
IDEA_WORDS = [
    'идея', 'хочу попробовать', 'а что если', 'было бы круто',
    'можно было бы', 'думаю запустить', 'хочу создать', 'хочу сделать',
    'придумала', 'придумал', 'интересно попробовать', 'а вдруг',
    'хочу запустить', 'мечтаю', 'было бы здорово',
]
NOTE_WORDS = [
    'запомни', 'запиши', 'заметка', 'зафиксируй', 'сохрани',
    'важно', 'отметь', 'на заметку', 'записать мысль', 'мысль',
]
DEADLINE_WORDS = [
    'сегодня', 'завтра', 'послезавтра', 'до ', 'к ', 'через ',
    'в пятницу', 'в субботу', 'в воскресенье', 'в понедельник',
    'во вторник', 'в среду', 'в четверг', 'на этой неделе', 'до конца',
]


def classify(text: str) -> str:
    t = text.lower().strip()

    # Удаление — проверяем первыми
    if any(w in t for w in DELETE_TASK_WORDS):  return 'delete_task'
    if any(w in t for w in DELETE_IDEA_WORDS):  return 'delete_idea'
    if any(w in t for w in DELETE_NOTE_WORDS):  return 'delete_note'

    # Запросы списков — ключевое слово темы + сигнал запроса (любой порядок)
    if _has_keyword(t, TASK_KEYWORDS) and _has_query_signal(t):  return 'query_tasks'
    if _has_keyword(t, IDEA_KEYWORDS) and _has_query_signal(t):  return 'query_ideas'
    if _has_keyword(t, NOTE_KEYWORDS) and _has_query_signal(t):  return 'query_notes'

    # Запрос только по ключевому слову без сигнала (например «задачи?», «заметки»)
    if t in ('задачи', 'задачи?', 'мои задачи'):                 return 'query_tasks'
    if t in ('идеи', 'идеи?', 'мои идеи'):                       return 'query_ideas'
    if t in ('заметки', 'заметки?', 'мои заметки'):              return 'query_notes'

    # Сохранение новой записи
    if any(w in t for w in NOTE_WORDS):         return 'note'
    if any(w in t for w in IDEA_WORDS):         return 'idea'
    if any(w in t for w in TASK_WORDS):         return 'task'
    if any(w in t for w in DEADLINE_WORDS):     return 'task'
    if t.endswith('?'):                          return 'note'
    return 'unknown'


# ─── Сохранение ──────────────────────────────────────────────────────────────
def save_task(text: str) -> bool:
    return save_to_sheet('Задачи',
        [now_samara(), text, 'Виктория', '', '🆕 Новая', '', 'Telegram', '', '', ''])

def save_idea(text: str) -> bool:
    return save_to_sheet('Идеи',
        [now_samara(), text, '💡 Новая', '🟡 Средний', '', ''])

def save_note(text: str) -> bool:
    return save_to_sheet('Заметки',
        [now_samara(), text, '', 'Telegram', ''])

def save_file(file_type: str, name: str, description: str, file_id: str, source: str) -> bool:
    return save_to_sheet('База',
        [now_samara(), file_type, name, description, file_id, source])


URL_RE = re.compile(r'https?://\S+|www\.\S+')


# ─── Загрузка данных из листов ───────────────────────────────────────────────
def load_active_tasks():
    """(row_1indexed, row_data) — только незавершённые задачи"""
    ws = get_sheet().worksheet('Задачи')
    result = []
    for i, r in enumerate(ws.get_all_values()[1:], start=2):
        if len(r) > 1 and r[1].strip() and '✅' not in (r[4] if len(r) > 4 else ''):
            result.append((i, r))
    return result

def load_ideas():
    """(row_1indexed, row_data) — все идеи кроме отклонённых"""
    ws = get_sheet().worksheet('Идеи')
    result = []
    for i, r in enumerate(ws.get_all_values()[1:], start=2):
        if len(r) > 1 and r[1].strip() and '🗑' not in (r[2] if len(r) > 2 else ''):
            result.append((i, r))
    return result

def load_notes():
    """(row_1indexed, row_data) — все заметки"""
    ws = get_sheet().worksheet('Заметки')
    result = []
    for i, r in enumerate(ws.get_all_values()[1:], start=2):
        if len(r) > 1 and r[1].strip():
            result.append((i, r))
    return result


# ─── Удаление по названию ────────────────────────────────────────────────────
def delete_row_by_name(sheet_name: str, name: str, col: int = 1) -> tuple[bool, str]:
    """Ищет строку по совпадению в колонке col (0-indexed), удаляет её."""
    try:
        ws = get_sheet().worksheet(sheet_name)
        name_lower = name.lower().strip()
        for i, r in enumerate(ws.get_all_values()[1:], start=2):
            if len(r) > col and name_lower in r[col].lower():
                found = r[col]
                ws.delete_rows(i)
                return True, found
        return False, name
    except Exception as e:
        logger.error(f"delete_row_by_name [{sheet_name}]: {e}")
        return False, name


# ─── Отправка списков с кнопками ─────────────────────────────────────────────
async def send_tasks_with_controls(send_fn, rows):
    today = datetime.now(SAMARA_TZ).date()
    if not rows:
        await send_fn("✨ Задач нет! Напиши что нужно сделать.")
        return

    now_str = datetime.now(SAMARA_TZ).strftime('%d.%m.%Y')
    text = f"📋 *Задачи на {now_str}* — открытых: *{len(rows)}*\n\n"
    keyboard = []

    for i, (row_idx, r) in enumerate(rows[:15], 1):
        status   = r[4] if len(r) > 4 else ''
        deadline = r[7] if len(r) > 7 else ''
        task     = r[1][:50] if len(r) > 1 else ''

        ico = '🔴' if '🔴' in status else '⚡' if '⚡' in status else '⏸' if '⏸' in status else '🆕'
        if deadline:
            try:
                if datetime.strptime(deadline.strip(), '%d.%m.%Y').date() < today:
                    ico = '🔴'
            except Exception:
                pass

        dl = f" _(до {deadline})_" if deadline else ''
        text += f"{i}. {ico} {task}{dl}\n"
        keyboard.append([
            InlineKeyboardButton(f"{i} ✅", callback_data=f"ta|done|{row_idx}"),
            InlineKeyboardButton(f"{i} ⚡", callback_data=f"ta|work|{row_idx}"),
            InlineKeyboardButton(f"{i} 🗑", callback_data=f"ta|del|{row_idx}"),
        ])

    if len(rows) > 15:
        text += f"\n_...ещё {len(rows)-15}_"
    text += "\n\n✅ готово  ⚡ в работе  🗑 удалить"

    await send_fn(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def send_ideas_with_controls(send_fn, rows):
    if not rows:
        await send_fn("💡 Идей пока нет! Напиши что хочешь попробовать.")
        return

    text = f"💡 *Идеи* — всего: *{len(rows)}*\n\n"
    keyboard = []

    STATUS_ICO = {'💡 Новая': '💡', '⚡ В разработке': '⚡', '✅ Запущена': '✅'}

    for i, (row_idx, r) in enumerate(rows[:15], 1):
        idea     = r[1][:50] if len(r) > 1 else ''
        status   = r[2] if len(r) > 2 else '💡 Новая'
        priority = r[3] if len(r) > 3 else ''
        ico = STATUS_ICO.get(status, '💡')
        prio = f" _{priority}_" if priority else ''
        text += f"{i}. {ico} {idea}{prio}\n"
        keyboard.append([
            InlineKeyboardButton(f"{i} ✅ Запущена",     callback_data=f"ia|launch|{row_idx}"),
            InlineKeyboardButton(f"{i} ⚡ В разработке", callback_data=f"ia|work|{row_idx}"),
            InlineKeyboardButton(f"{i} 🗑 Удалить",      callback_data=f"ia|del|{row_idx}"),
        ])

    if len(rows) > 15:
        text += f"\n_...ещё {len(rows)-15}_"
    text += "\n\n✅ запустить  ⚡ в разработку  🗑 удалить"

    await send_fn(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def send_notes_with_controls(send_fn, rows):
    if not rows:
        await send_fn("📝 Заметок пока нет! Напиши «запомни …»")
        return

    text = f"📝 *Заметки* — всего: *{len(rows)}*\n\n"
    keyboard = []

    for i, (row_idx, r) in enumerate(rows[:15], 1):
        note = r[1][:60] if len(r) > 1 else ''
        date = r[0][:10] if len(r) > 0 else ''
        text += f"{i}. {note} _({date})_\n"
        keyboard.append([
            InlineKeyboardButton(f"{i} 🗑 Удалить", callback_data=f"no|del|{row_idx}"),
        ])

    if len(rows) > 15:
        text += f"\n_...ещё {len(rows)-15}_"

    await send_fn(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ─── Хелпер: извлечь название после триггера ─────────────────────────────────
def extract_name(text: str, triggers: list[str]) -> str:
    t = text.lower()
    for trigger in triggers:
        if trigger in t:
            idx = t.index(trigger) + len(trigger)
            return text[idx:].strip(' :«»"\'')
    return ''


# ─── Handlers ─────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        context.job_queue.run_daily(
            daily_digest,
            time=datetime.strptime("09:00", "%H:%M").replace(tzinfo=SAMARA_TZ).timetz(),
            chat_id=chat_id,
            name=f"digest_{chat_id}",
        )
    except Exception as e:
        logger.error(f"Job schedule error: {e}")

    await update.message.reply_text(
        "Привет! Я Фунтик 🐾\n\n"
        "Напиши что угодно — сама разберусь куда сохранить:\n\n"
        "✅ *Задача* — «надо», «купить», «не забыть»\n"
        "💡 *Идея* — «хочу попробовать», «а что если»\n"
        "📝 *Заметка* — «запомни», «важно»\n\n"
        "*Управление:*\n"
        "— «какие задачи» / «мои идеи» / «мои заметки»\n"
        "— «удали задачу/идею/заметку [название]»\n"
        "/help — полная справка",
        parse_mode="Markdown"
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Ссылки в тексте → «База»
    links = _extract_links(text)
    if links:
        # Сохраняем каждую ссылку; описание = остальной текст без ссылки
        description = URL_RE.sub('', text).strip(' \n-—|')
        for url in links:
            save_file('🔗 Ссылка', url[:260], description[:200], '', 'Telegram')
        names = '\n'.join(f'• {u[:80]}' for u in links[:5])
        await update.message.reply_text(
            f"🔗 {'Ссылка сохранена' if len(links)==1 else f'{len(links)} ссылки сохранены'} в «Базу»:\n{names}",
            parse_mode="Markdown")
        return

    category = classify(text)

    # ── Показать списки ──
    if category == 'query_tasks':
        await send_tasks_with_controls(update.message.reply_text, load_active_tasks())
        return
    if category == 'query_ideas':
        await send_ideas_with_controls(update.message.reply_text, load_ideas())
        return
    if category == 'query_notes':
        await send_notes_with_controls(update.message.reply_text, load_notes())
        return

    # ── Удалить по названию ──
    if category == 'delete_task':
        name = extract_name(text, DELETE_TASK_WORDS)
        ok, found = delete_row_by_name('Задачи', name)
        await update.message.reply_text(
            f"🗑 Задача удалена:\n_{found}_" if ok
            else f"❌ Не нашла задачу «{name}». Напиши «какие задачи» чтобы увидеть список.",
            parse_mode="Markdown")
        return

    if category == 'delete_idea':
        name = extract_name(text, DELETE_IDEA_WORDS)
        ok, found = delete_row_by_name('Идеи', name)
        await update.message.reply_text(
            f"🗑 Идея удалена:\n_{found}_" if ok
            else f"❌ Не нашла идею «{name}». Напиши «мои идеи» чтобы увидеть список.",
            parse_mode="Markdown")
        return

    if category == 'delete_note':
        name = extract_name(text, DELETE_NOTE_WORDS)
        ok, found = delete_row_by_name('Заметки', name)
        await update.message.reply_text(
            f"🗑 Заметка удалена:\n_{found}_" if ok
            else f"❌ Не нашла заметку «{name}». Напиши «мои заметки» чтобы увидеть список.",
            parse_mode="Markdown")
        return

    # ── Сохранить ──
    if category == 'task':
        ok = save_task(text)
        await update.message.reply_text(
            f"✅ Задача записана:\n_{text}_" if ok else "❌ Ошибка сохранения",
            parse_mode="Markdown")

    elif category == 'idea':
        ok = save_idea(text)
        await update.message.reply_text(
            f"💡 Идея сохранена:\n_{text}_" if ok else "❌ Ошибка сохранения",
            parse_mode="Markdown")

    elif category == 'note':
        ok = save_note(text)
        await update.message.reply_text(
            f"📝 Заметка сохранена:\n_{text}_" if ok else "❌ Ошибка сохранения",
            parse_mode="Markdown")

    else:
        context.user_data['pending_text'] = text
        short = text[:50].replace('|', '')
        await update.message.reply_text(
            f"Куда сохранить?\n\n_«{text[:100]}»_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Задача",   callback_data=f"save|task|{short}"),
                InlineKeyboardButton("💡 Идея",    callback_data=f"save|idea|{short}"),
                InlineKeyboardButton("📝 Заметка", callback_data=f"save|note|{short}"),
            ]])
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts  = query.data.split('|')
    action = parts[0]

    # ── Сохранить в нужную категорию ──
    if action == 'save' and len(parts) >= 2:
        cat  = parts[1]
        text = context.user_data.get('pending_text', parts[2] if len(parts) > 2 else '')
        if cat == 'task':
            ok = save_task(text);  msg = f"✅ Задача:\n_{text[:100]}_"
        elif cat == 'idea':
            ok = save_idea(text);  msg = f"💡 Идея:\n_{text[:100]}_"
        else:
            ok = save_note(text);  msg = f"📝 Заметка:\n_{text[:100]}_"
        if not ok: msg = "❌ Ошибка сохранения"
        await query.edit_message_text(msg, parse_mode="Markdown")
        context.user_data.pop('pending_text', None)
        return

    # ── Управление задачами: ta|{действие}|{row} ──
    if action == 'ta' and len(parts) == 3:
        act, row_idx = parts[1], int(parts[2])
        try:
            ws = get_sheet().worksheet('Задачи')
            name = ws.row_values(row_idx)[1] if ws.row_values(row_idx) else f"строка {row_idx}"
            if act == 'done':
                ws.update_cell(row_idx, 5, '✅ Готово')
                ws.update_cell(row_idx, 6, '100')
                ws.update_cell(row_idx, 9, now_samara())
                msg = f"✅ Выполнено:\n_{name}_"
            elif act == 'work':
                ws.update_cell(row_idx, 5, '⚡ В работе')
                ws.update_cell(row_idx, 6, '50')
                msg = f"⚡ В работе:\n_{name}_"
            elif act == 'del':
                ws.delete_rows(row_idx)
                msg = f"🗑 Удалено:\n_{name}_"
            else:
                return
            await query.edit_message_text(msg, parse_mode="Markdown")
            # Обновить список
            rows = load_active_tasks()
            if rows:
                chat_id = query.message.chat_id
                await send_tasks_with_controls(
                    lambda t, **kw: context.bot.send_message(chat_id=chat_id, text=t, **kw), rows)
        except Exception as e:
            logger.error(f"ta callback: {e}")
            await query.edit_message_text("❌ Ошибка обновления задачи")
        return

    # ── Управление идеями: ia|{действие}|{row} ──
    if action == 'ia' and len(parts) == 3:
        act, row_idx = parts[1], int(parts[2])
        try:
            ws = get_sheet().worksheet('Идеи')
            name = ws.row_values(row_idx)[1] if ws.row_values(row_idx) else f"строка {row_idx}"
            if act == 'launch':
                ws.update_cell(row_idx, 3, '✅ Запущена')
                msg = f"✅ Запущена:\n_{name}_"
            elif act == 'work':
                ws.update_cell(row_idx, 3, '⚡ В разработке')
                msg = f"⚡ В разработке:\n_{name}_"
            elif act == 'del':
                ws.delete_rows(row_idx)
                msg = f"🗑 Удалено:\n_{name}_"
            else:
                return
            await query.edit_message_text(msg, parse_mode="Markdown")
            rows = load_ideas()
            if rows:
                chat_id = query.message.chat_id
                await send_ideas_with_controls(
                    lambda t, **kw: context.bot.send_message(chat_id=chat_id, text=t, **kw), rows)
        except Exception as e:
            logger.error(f"ia callback: {e}")
            await query.edit_message_text("❌ Ошибка обновления идеи")
        return

    # ── Управление заметками: no|del|{row} ──
    if action == 'no' and len(parts) == 3:
        act, row_idx = parts[1], int(parts[2])
        try:
            ws = get_sheet().worksheet('Заметки')
            name = ws.row_values(row_idx)[1] if ws.row_values(row_idx) else f"строка {row_idx}"
            if act == 'del':
                ws.delete_rows(row_idx)
                msg = f"🗑 Заметка удалена:\n_{name}_"
            else:
                return
            await query.edit_message_text(msg, parse_mode="Markdown")
            rows = load_notes()
            if rows:
                chat_id = query.message.chat_id
                await send_notes_with_controls(
                    lambda t, **kw: context.bot.send_message(chat_id=chat_id, text=t, **kw), rows)
        except Exception as e:
            logger.error(f"no callback: {e}")
            await query.edit_message_text("❌ Ошибка удаления заметки")
        return


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎙 Голосовые пока не поддерживаются — напиши текстом!")


# ─── Медиафайлы и ссылки → «База» ────────────────────────────────────────────
def _forwarded_from(msg) -> str:
    """Имя источника при пересылке."""
    if msg.forward_from:
        fn = msg.forward_from.first_name or ''
        ln = msg.forward_from.last_name or ''
        return f"Telegram: {(fn + ' ' + ln).strip()}"
    if msg.forward_from_chat:
        return f"Канал: {msg.forward_from_chat.title or ''}"
    if msg.forward_sender_name:
        return f"Telegram: {msg.forward_sender_name}"
    return 'Telegram'


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg    = update.message
    photo  = msg.photo[-1]  # наибольшее разрешение
    cap    = msg.caption or ''
    source = _forwarded_from(msg)
    ok = save_file('📷 Фото', 'Фото', cap[:200], photo.file_id, source)
    await msg.reply_text(
        f"📷 Фото сохранено в «Базу»{f': _{cap[:60]}_' if cap else ''}" if ok
        else "❌ Ошибка сохранения фото",
        parse_mode="Markdown")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg      = update.message
    doc      = msg.document
    name     = doc.file_name or 'Документ'
    cap      = msg.caption or ''
    source   = _forwarded_from(msg)
    ok = save_file('📄 Документ', name[:200], cap[:200], doc.file_id, source)
    await msg.reply_text(
        f"📄 Документ сохранён в «Базу»: _{name[:60]}_" if ok
        else "❌ Ошибка сохранения документа",
        parse_mode="Markdown")


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg    = update.message
    video  = msg.video
    cap    = msg.caption or ''
    source = _forwarded_from(msg)
    name   = video.file_name or 'Видео'
    ok = save_file('🎥 Видео', name[:200], cap[:200], video.file_id, source)
    await msg.reply_text(
        f"🎥 Видео сохранено в «Базу»{f': _{cap[:60]}_' if cap else ''}" if ok
        else "❌ Ошибка сохранения видео",
        parse_mode="Markdown")


def _extract_links(text: str) -> list[str]:
    return URL_RE.findall(text)


# ─── Ежедневный дайджест ──────────────────────────────────────────────────────
async def daily_digest(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    try:
        rows  = load_active_tasks()
        today = datetime.now(SAMARA_TZ).date()

        if not rows:
            await context.bot.send_message(
                chat_id=chat_id,
                text="☀️ Доброе утро! Задач нет — отличный день 🎯")
            return

        overdue, in_work, new_tasks = [], [], []
        for _, r in rows:
            status   = r[4] if len(r) > 4 else ''
            task     = r[1] if len(r) > 1 else ''
            deadline = r[7] if len(r) > 7 else ''
            is_late  = False
            if deadline:
                try:
                    if datetime.strptime(deadline.strip(), '%d.%m.%Y').date() < today:
                        is_late = True
                except Exception:
                    pass
            entry = (task, deadline)
            if is_late or '🔴' in status: overdue.append(entry)
            elif '⚡' in status:          in_work.append(entry)
            else:                         new_tasks.append(entry)

        def fmt(lst):
            return '\n'.join(
                f"  • {t[:50]}" + (f" _(до {dl})_" if dl else '')
                for t, dl in lst[:5])

        now_str = datetime.now(SAMARA_TZ).strftime('%d.%m.%Y')
        text = f"☀️ *Доброе утро! {now_str}*\nОткрытых задач: *{len(rows)}*\n\n"
        if overdue:    text += f"🔴 *Просрочено ({len(overdue)}):*\n{fmt(overdue)}\n\n"
        if in_work:    text += f"⚡ *В работе ({len(in_work)}):*\n{fmt(in_work)}\n\n"
        if new_tasks:  text += f"🆕 *Новые ({len(new_tasks)}):*\n{fmt(new_tasks)}\n\n"
        text += "Хорошего дня! 🚀"

        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Digest error: {e}")


# ─── Команды ─────────────────────────────────────────────────────────────────
async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_tasks_with_controls(update.message.reply_text, load_active_tasks())

async def cmd_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_ideas_with_controls(update.message.reply_text, load_ideas())

async def cmd_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_notes_with_controls(update.message.reply_text, load_notes())

async def cmd_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ws   = get_sheet().worksheet('База')
        rows = [r for r in ws.get_all_values()[1:] if len(r) > 2 and r[2].strip()]
        if not rows:
            await update.message.reply_text("📁 База пуста — перешли мне фото, документ или ссылку.")
            return
        text = f"📁 *База файлов* — всего: *{len(rows)}*\n\n"
        for r in rows[-20:]:  # последние 20
            date = r[0][:10] if len(r) > 0 else ''
            typ  = r[1] if len(r) > 1 else ''
            name = r[2][:60] if len(r) > 2 else ''
            text += f"{typ} {name} _({date})_\n"
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"cmd_files: {e}")
        await update.message.reply_text("❌ Ошибка загрузки базы")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🐾 *Фунтик умеет:*\n\n"
        "*Сохранить:*\n"
        "✅ Задача — «надо», «нужно», «купить»...\n"
        "💡 Идея — «хочу попробовать», «а что если»...\n"
        "📝 Заметка — «запомни», «важно»...\n\n"
        "*Смотреть и управлять:*\n"
        "— «какие задачи» или /tasks\n"
        "— «мои идеи» или /ideas\n"
        "— «мои заметки» или /notes\n\n"
        "*Удалить:*\n"
        "— «удали задачу [название]»\n"
        "— «удали идею [название]»\n"
        "— «удали заметку [текст]»\n\n"
        "*Кнопки в списке задач:*\n"
        "✅ выполнено  ⚡ в работе  🗑 удалить\n\n"
        "*Кнопки в списке идей:*\n"
        "✅ запустить  ⚡ в разработку  🗑 удалить\n\n"
        "*База файлов /files:*\n"
        "📷 Фото — перешли фото или скрин\n"
        "📄 Документ — перешли файл\n"
        "🎥 Видео — перешли видео\n"
        "🔗 Ссылка — отправь URL\n\n"
        "📬 Дайджест каждый день в 9:00 по Самаре",
        parse_mode="Markdown"
    )


# ─── Запуск ───────────────────────────────────────────────────────────────────
def main():
    proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    if proxy:
        from telegram.request import HTTPXRequest
        app = Application.builder().token(BOT_TOKEN).request(HTTPXRequest(proxy=proxy)).build()
    else:
        app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("tasks",  cmd_tasks))
    app.add_handler(CommandHandler("ideas",  cmd_ideas))
    app.add_handler(CommandHandler("notes",  cmd_notes))
    app.add_handler(CommandHandler("files",  cmd_files))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO,    handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.VIDEO,    handle_video))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("✅ Фунтик запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
