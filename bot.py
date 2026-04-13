#!/usr/bin/env python3
"""
Бот Фунтик — умный ассистент Виктории
Задачи / Идеи / Заметки + управление задачами + ежедневный дайджест 9:00 Самара
"""

import os
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
TASK_QUERY_WORDS = [
    'какие задачи', 'список задач', 'мои задачи', 'покажи задачи',
    'что в работе', 'задачи на сегодня', 'что надо сделать',
    'текущие задачи', 'активные задачи', 'что там по задачам',
]

DELETE_WORDS = ['удали задачу', 'удалить задачу', 'убери задачу', 'удали таск']

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
    'хочу запустить', 'мечтаю', 'было бы здорово', 'а если попробовать',
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

    # Удаление задачи
    if any(w in t for w in DELETE_WORDS):
        return 'delete_task'

    # Запрос списка
    if any(w in t for w in TASK_QUERY_WORDS):
        return 'query_tasks'

    if any(w in t for w in NOTE_WORDS):
        return 'note'
    if any(w in t for w in IDEA_WORDS):
        return 'idea'
    if any(w in t for w in TASK_WORDS):
        return 'task'
    if any(w in t for w in DEADLINE_WORDS):
        return 'task'
    if t.endswith('?'):
        return 'note'

    return 'unknown'


# ─── Сохранение ──────────────────────────────────────────────────────────────
def save_task(text: str) -> bool:
    now = now_samara()
    return save_to_sheet('Задачи', [now, text, 'Виктория', '', '🆕 Новая', '', 'Telegram', '', '', ''])


def save_idea(text: str) -> bool:
    now = now_samara()
    return save_to_sheet('Идеи', [now, text, '💡 Новая', '🟡 Средний', '', ''])


def save_note(text: str) -> bool:
    now = now_samara()
    return save_to_sheet('Заметки', [now, text, '', 'Telegram', ''])


# ─── Получение активных задач с индексами строк ───────────────────────────────
def load_active_tasks():
    """
    Возвращает список (sheet_row_1indexed, row_data) только незавершённых задач.
    sheet_row — реальный номер строки в таблице (1-indexed, строка 1 = шапка).
    """
    ws   = get_sheet().worksheet('Задачи')
    all_rows = ws.get_all_values()
    result = []
    for i, r in enumerate(all_rows[1:], start=2):   # start=2: строка 1 — шапка
        if len(r) > 1 and r[1].strip():
            status = r[4] if len(r) > 4 else ''
            if '✅' not in status:
                result.append((i, r))
    return result


# ─── Показ задач с кнопками управления ───────────────────────────────────────
async def send_tasks_with_controls(send_fn, active_rows):
    """
    Отправляет одно сообщение: список задач + кнопки управления под каждой.
    send_fn — корутина для отправки (update.message.reply_text или query.edit_message_text).
    """
    today = datetime.now(SAMARA_TZ).date()

    if not active_rows:
        await send_fn("✨ Все задачи выполнены! Напиши мне что-нибудь новое 🎯")
        return

    now_str = datetime.now(SAMARA_TZ).strftime('%d.%m.%Y')
    text = f"📋 *Задачи на {now_str}* — всего открытых: *{len(active_rows)}*\n\n"

    keyboard = []
    for i, (row_idx, r) in enumerate(active_rows[:15], 1):
        task     = r[1] if len(r) > 1 else ''
        status   = r[4] if len(r) > 4 else ''
        deadline = r[7] if len(r) > 7 else ''

        # Эмодзи статуса
        if '🔴' in status:
            s_ico = '🔴'
        elif '⚡' in status:
            s_ico = '⚡'
        elif '⏸' in status:
            s_ico = '⏸'
        else:
            s_ico = '🆕'

        # Просрочена?
        if deadline:
            try:
                dl = datetime.strptime(deadline.strip(), '%d.%m.%Y').date()
                if dl < today and '🔴' not in status:
                    s_ico = '🔴'
            except Exception:
                pass

        dl_text = f" _(до {deadline})_" if deadline else ''
        text += f"{i}. {s_ico} {task[:50]}{dl_text}\n"

        # Кнопки для этой задачи
        keyboard.append([
            InlineKeyboardButton(f"{i} ✅ Готово",   callback_data=f"ta|done|{row_idx}"),
            InlineKeyboardButton(f"{i} ⚡ В работе", callback_data=f"ta|work|{row_idx}"),
            InlineKeyboardButton(f"{i} 🗑 Удалить",  callback_data=f"ta|del|{row_idx}"),
        ])

    if len(active_rows) > 15:
        text += f"\n_...и ещё {len(active_rows) - 15} задач_"

    text += "\n\nНажми кнопку чтобы изменить статус или удалить:"

    await send_fn(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ─── Удаление задачи по названию ─────────────────────────────────────────────
def delete_task_by_name(name: str) -> tuple[bool, str]:
    """
    Ищет задачу по совпадению названия (регистр не важен).
    Возвращает (успех, название задачи или сообщение об ошибке).
    """
    try:
        ws = get_sheet().worksheet('Задачи')
        rows = ws.get_all_values()
        name_lower = name.lower().strip()

        for i, r in enumerate(rows[1:], start=2):
            if len(r) > 1 and name_lower in r[1].lower():
                task_name = r[1]
                ws.delete_rows(i)
                return True, task_name

        return False, name
    except Exception as e:
        logger.error(f"delete_task_by_name error: {e}")
        return False, name


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
        "✅ *Задача* — «надо позвонить», «купить», «не забыть…»\n"
        "💡 *Идея* — «хочу попробовать», «а что если…»\n"
        "📝 *Заметка* — «запомни», «важно», любая мысль\n\n"
        "📋 *Управление задачами:*\n"
        "— «какие задачи» — список с кнопками ✅ ⚡ 🗑\n"
        "— «удали задачу [название]» — удалить по названию\n\n"
        "Если не пойму — спрошу сама 👇",
        parse_mode="Markdown"
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    t    = text.lower()
    category = classify(text)

    # ── Показать задачи с кнопками управления ──
    if category == 'query_tasks':
        try:
            active = load_active_tasks()
            await send_tasks_with_controls(update.message.reply_text, active)
        except Exception as e:
            logger.error(e)
            await update.message.reply_text("❌ Не удалось загрузить задачи")
        return

    # ── Удалить задачу по названию ──
    if category == 'delete_task':
        # Вырезаем название: всё после триггерного слова
        task_name = text
        for trigger in DELETE_WORDS:
            if trigger in t:
                idx = t.index(trigger) + len(trigger)
                task_name = text[idx:].strip(' :«»"\'')
                break

        if not task_name:
            await update.message.reply_text(
                "Напиши как называется задача:\n_удали задачу [название]_",
                parse_mode="Markdown")
            return

        ok, found = delete_task_by_name(task_name)
        if ok:
            await update.message.reply_text(f"🗑 Задача удалена:\n_{found}_", parse_mode="Markdown")
        else:
            await update.message.reply_text(
                f"❌ Не нашла задачу с названием «{task_name}»\n"
                "Попробуй написать часть названия или напиши «какие задачи» чтобы увидеть список.",
                parse_mode="Markdown")
        return

    # ── Сохранить задачу ──
    if category == 'task':
        ok = save_task(text)
        await update.message.reply_text(
            f"✅ Задача записана:\n_{text}_" if ok else "❌ Не удалось сохранить",
            parse_mode="Markdown")

    elif category == 'idea':
        ok = save_idea(text)
        await update.message.reply_text(
            f"💡 Идея сохранена:\n_{text}_" if ok else "❌ Не удалось сохранить",
            parse_mode="Markdown")

    elif category == 'note':
        ok = save_note(text)
        await update.message.reply_text(
            f"📝 Заметка сохранена:\n_{text}_" if ok else "❌ Не удалось сохранить",
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

    parts = query.data.split('|')
    action = parts[0]

    # ── Сохранить в нужную категорию ──
    if action == 'save' and len(parts) >= 2:
        cat  = parts[1]
        text = context.user_data.get('pending_text', parts[2] if len(parts) > 2 else '')
        if cat == 'task':
            ok = save_task(text)
            msg = f"✅ Задача записана:\n_{text[:100]}_" if ok else "❌ Ошибка"
        elif cat == 'idea':
            ok = save_idea(text)
            msg = f"💡 Идея сохранена:\n_{text[:100]}_" if ok else "❌ Ошибка"
        else:
            ok = save_note(text)
            msg = f"📝 Заметка сохранена:\n_{text[:100]}_" if ok else "❌ Ошибка"
        await query.edit_message_text(msg, parse_mode="Markdown")
        context.user_data.pop('pending_text', None)
        return

    # ── Управление задачей: ta|{действие}|{row} ──
    if action == 'ta' and len(parts) >= 3:
        act = parts[1]
        try:
            row_idx = int(parts[2])
        except ValueError:
            return

        try:
            ws = get_sheet().worksheet('Задачи')
            r  = ws.row_values(row_idx)
            task_name = r[1] if len(r) > 1 else f"строка {row_idx}"

            if act == 'done':
                now = now_samara()
                ws.update_cell(row_idx, 5, '✅ Готово')       # Статус
                ws.update_cell(row_idx, 6, '100')              # % выполнения
                ws.update_cell(row_idx, 9, now)                # Дата закрытия
                msg = f"✅ Отмечено как выполнено:\n_{task_name}_"

            elif act == 'work':
                ws.update_cell(row_idx, 5, '⚡ В работе')
                ws.update_cell(row_idx, 6, '50')
                msg = f"⚡ Переведено в работу:\n_{task_name}_"

            elif act == 'del':
                ws.delete_rows(row_idx)
                msg = f"🗑 Задача удалена:\n_{task_name}_"

            else:
                return

            await query.edit_message_text(msg, parse_mode="Markdown")

            # Обновляем список задач после изменения
            active = load_active_tasks()
            if active:
                await send_tasks_with_controls(
                    lambda t, **kw: context.bot.send_message(
                        chat_id=query.message.chat_id, text=t, **kw),
                    active
                )

        except Exception as e:
            logger.error(f"Task action error: {e}")
            await query.edit_message_text("❌ Ошибка при обновлении задачи")


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎙 Голосовые пока не поддерживаются — напиши текстом!")


# ─── Ежедневный дайджест ──────────────────────────────────────────────────────
async def daily_digest(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    try:
        active = load_active_tasks()
        today  = datetime.now(SAMARA_TZ).date()

        if not active:
            await context.bot.send_message(
                chat_id=chat_id,
                text="☀️ Доброе утро! Задач пока нет — отличный день 🎯")
            return

        overdue, in_work, new_tasks = [], [], []
        for _, r in active:
            status   = r[4] if len(r) > 4 else ''
            task     = r[1] if len(r) > 1 else ''
            deadline = r[7] if len(r) > 7 else ''

            is_late = False
            if deadline:
                try:
                    if datetime.strptime(deadline.strip(), '%d.%m.%Y').date() < today:
                        is_late = True
                except Exception:
                    pass

            entry = (task, deadline)
            if is_late or '🔴' in status:
                overdue.append(entry)
            elif '⚡' in status:
                in_work.append(entry)
            else:
                new_tasks.append(entry)

        now_str = datetime.now(SAMARA_TZ).strftime('%d.%m.%Y')
        text = f"☀️ *Доброе утро! {now_str}*\nОткрытых задач: *{len(active)}*\n\n"

        def fmt(lst):
            return '\n'.join(
                f"  • {t[:50]}" + (f" _(до {dl})_" if dl else '')
                for t, dl in lst[:5]
            )

        if overdue:   text += f"🔴 *Просрочено ({len(overdue)}):*\n{fmt(overdue)}\n\n"
        if in_work:   text += f"⚡ *В работе ({len(in_work)}):*\n{fmt(in_work)}\n\n"
        if new_tasks: text += f"🆕 *Новые ({len(new_tasks)}):*\n{fmt(new_tasks)}\n\n"

        text += "Хорошего дня! 🚀"

        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Digest error: {e}")


# ─── Команды ─────────────────────────────────────────────────────────────────
async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        active = load_active_tasks()
        await send_tasks_with_controls(update.message.reply_text, active)
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("❌ Не удалось загрузить задачи")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🐾 *Фунтик умеет:*\n\n"
        "*Сохранить:*\n"
        "✅ Задача — «надо», «нужно», «купить», «не забыть»...\n"
        "💡 Идея — «хочу попробовать», «а что если»...\n"
        "📝 Заметка — «запомни», «важно», мысли...\n\n"
        "*Управлять задачами:*\n"
        "— «какие задачи» — список с кнопками\n"
        "— «удали задачу [название]» — удалить\n"
        "— /tasks — то же самое\n\n"
        "*Кнопки в списке:*\n"
        "✅ Готово — отметить выполненной\n"
        "⚡ В работе — взять в работу\n"
        "🗑 Удалить — убрать из списка\n\n"
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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tasks", cmd_tasks))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO, handle_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("✅ Фунтик запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
