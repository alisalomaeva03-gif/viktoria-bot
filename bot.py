#!/usr/bin/env python3
"""
Бот Фунтик — умный ассистент Виктории
Задачи / Идеи / Заметки + ежедневный дайджест в 9:00 по Самаре
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


# ─── Классификация сообщений ─────────────────────────────────────────────────
TASK_WORDS = [
    'надо', 'нужно', 'сделать', 'позвонить', 'написать', 'отправить',
    'встретиться', 'купить', 'оплатить', 'подготовить', 'договориться',
    'не забыть', 'напомни', 'поставить', 'узнать', 'проверить',
    'запланировать', 'созвониться', 'отвезти', 'забрать', 'сдать',
    'починить', 'разобраться', 'решить', 'завершить', 'доделать',
    'задача', 'поставь задачу', 'запись в задачи'
]

IDEA_WORDS = [
    'идея', 'хочу попробовать', 'а что если', 'было бы круто',
    'можно было бы', 'думаю запустить', 'хочу создать', 'хочу сделать',
    'придумала', 'придумал', 'интересно попробовать', 'а вдруг',
    'запусти проект', 'хочу запустить', 'мечтаю', 'было бы здорово',
    'а если попробовать'
]

NOTE_WORDS = [
    'запомни', 'запиши', 'заметка', 'зафиксируй', 'сохрани',
    'важно', 'отметь', 'на заметку', 'не забудь записать',
    'записать мысль', 'мысль'
]

DEADLINE_WORDS = [
    'сегодня', 'завтра', 'послезавтра', 'до ', 'к ', 'через ',
    'в пятницу', 'в субботу', 'в воскресенье', 'в понедельник',
    'во вторник', 'в среду', 'в четверг', 'на этой неделе', 'до конца'
]


def classify(text: str) -> str:
    """
    Возвращает: 'task', 'idea', 'note', 'unknown'
    'unknown' — показываем меню выбора
    """
    t = text.lower()

    # Явные маркеры заметки
    if any(w in t for w in NOTE_WORDS):
        return 'note'

    # Явные маркеры идеи
    if any(w in t for w in IDEA_WORDS):
        return 'idea'

    # Явные маркеры задачи
    if any(w in t for w in TASK_WORDS):
        return 'task'

    # Дедлайн в тексте → скорее задача
    if any(w in t for w in DEADLINE_WORDS):
        return 'task'

    # Вопросительные — заметка
    if t.endswith('?'):
        return 'note'

    # Короткий текст без маркеров — неизвестно, покажем меню
    return 'unknown'


# ─── Сохранение по типу ───────────────────────────────────────────────────────
def save_task(text: str) -> bool:
    now = now_samara()
    # Дата, Задача, Ответственный, Категория, Статус, %, Источник, Срок, Дата закрытия, Причина
    return save_to_sheet('Задачи', [now, text, 'Виктория', '', '🆕 Новая', '', 'Telegram', '', '', ''])


def save_idea(text: str) -> bool:
    now = now_samara()
    return save_to_sheet('Идеи', [now, text, '', '💡 Новая', ''])


def save_note(text: str) -> bool:
    now = now_samara()
    return save_to_sheet('Заметки', [now, text])


# ─── Клавиатура выбора категории ──────────────────────────────────────────────
def category_keyboard(text: str) -> InlineKeyboardMarkup:
    """Инлайн-меню: что сохранить?"""
    # Передаём текст через callback_data (обрезаем до 50 символов для безопасности)
    short = text[:50].replace('|', '')
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Задача",  callback_data=f"save|task|{short}"),
            InlineKeyboardButton("💡 Идея",   callback_data=f"save|idea|{short}"),
            InlineKeyboardButton("📝 Заметка", callback_data=f"save|note|{short}"),
        ]
    ])


# ─── Handlers ─────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    context.user_data['chat_id'] = chat_id

    # Ежедневный дайджест в 9:00 по Самаре
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
        "Просто напиши мне что угодно — я сама разберусь куда сохранить:\n\n"
        "✅ *Задача* — «надо позвонить», «купить», «не забыть…»\n"
        "💡 *Идея* — «хочу попробовать», «а что если…»\n"
        "📝 *Заметка* — «запомни», «важно», любая мысль\n\n"
        "Если не пойму — спрошу сама 👇",
        parse_mode="Markdown"
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    category = classify(text)

    if category == 'task':
        ok = save_task(text)
        msg = f"✅ Задача записана:\n_{text}_" if ok else "❌ Не удалось сохранить, попробуй ещё раз"
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif category == 'idea':
        ok = save_idea(text)
        msg = f"💡 Идея сохранена:\n_{text}_" if ok else "❌ Не удалось сохранить"
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif category == 'note':
        ok = save_note(text)
        msg = f"📝 Заметка сохранена:\n_{text}_" if ok else "❌ Не удалось сохранить"
        await update.message.reply_text(msg, parse_mode="Markdown")

    else:
        # Не понял — показываем меню
        # Сохраняем полный текст в user_data (callback_data ограничена по длине)
        context.user_data['pending_text'] = text
        await update.message.reply_text(
            f"Куда сохранить это?\n\n_«{text[:100]}»_",
            parse_mode="Markdown",
            reply_markup=category_keyboard(text)
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split('|')
    if len(data) < 2:
        return

    action, cat = data[0], data[1]
    # Берём полный текст из user_data (там он без обрезки)
    text = context.user_data.get('pending_text', data[2] if len(data) > 2 else "")

    if action == 'save':
        if cat == 'task':
            ok = save_task(text)
            msg = f"✅ Задача записана:\n_{text[:100]}_" if ok else "❌ Ошибка сохранения"
        elif cat == 'idea':
            ok = save_idea(text)
            msg = f"💡 Идея сохранена:\n_{text[:100]}_" if ok else "❌ Ошибка сохранения"
        else:
            ok = save_note(text)
            msg = f"📝 Заметка сохранена:\n_{text[:100]}_" if ok else "❌ Ошибка сохранения"

        await query.edit_message_text(msg, parse_mode="Markdown")
        context.user_data.pop('pending_text', None)


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎙 Голосовые пока не поддерживаются — напиши текстом!")


# ─── Ежедневный дайджест ──────────────────────────────────────────────────────
async def daily_digest(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    try:
        ws = get_sheet().worksheet('Задачи')
        rows = [r for r in ws.get_all_values()[1:] if len(r) > 1 and r[1].strip()]

        if not rows:
            await context.bot.send_message(chat_id=chat_id,
                text="☀️ Доброе утро! Задач пока нет — отличный день чтобы начать 🎯")
            return

        overdue, active, new_tasks = [], [], []
        today = datetime.now(SAMARA_TZ).date()

        for r in rows:
            status  = r[4] if len(r) > 4 else ''
            task    = r[1] if len(r) > 1 else ''
            deadline_str = r[7] if len(r) > 7 else ''

            if '✅' in status:
                continue  # пропускаем завершённые

            # Проверяем просроченность
            is_overdue = False
            if deadline_str:
                try:
                    dl = datetime.strptime(deadline_str.strip(), '%d.%m.%Y').date()
                    if dl < today:
                        is_overdue = True
                except Exception:
                    pass

            if is_overdue or '🔴' in status:
                overdue.append((task, deadline_str))
            elif '⚡' in status:
                active.append((task, deadline_str))
            else:
                new_tasks.append((task, deadline_str))

        # Формируем сообщение
        now_str = datetime.now(SAMARA_TZ).strftime('%d.%m.%Y')
        text = f"☀️ *Доброе утро! Задачи на {now_str}*\n\n"

        total_open = len(overdue) + len(active) + len(new_tasks)
        text += f"Всего открытых: *{total_open}*\n\n"

        if overdue:
            text += f"🔴 *Просрочено ({len(overdue)}):*\n"
            for t, dl in overdue[:5]:
                dl_txt = f" (до {dl})" if dl else ""
                text += f"  • {t[:50]}{dl_txt}\n"
            text += "\n"

        if active:
            text += f"⚡ *В работе ({len(active)}):*\n"
            for t, dl in active[:5]:
                dl_txt = f" (до {dl})" if dl else ""
                text += f"  • {t[:50]}{dl_txt}\n"
            text += "\n"

        if new_tasks:
            text += f"🆕 *Новые ({len(new_tasks)}):*\n"
            for t, dl in new_tasks[:5]:
                dl_txt = f" (до {dl})" if dl else ""
                text += f"  • {t[:50]}{dl_txt}\n"

        text += "\nХорошего дня! 🚀"

        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Digest error: {e}")


# ─── Команды ─────────────────────────────────────────────────────────────────
async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручной вызов дайджеста /tasks"""
    # Имитируем job для вызова daily_digest вручную
    class FakeJob:
        chat_id = update.effective_chat.id
    class FakeContext:
        job = FakeJob()
        bot = context.bot
    await daily_digest(FakeContext())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🐾 *Фунтик умеет:*\n\n"
        "Просто напиши текст — я пойму куда сохранить:\n\n"
        "✅ *Задача* — «надо», «нужно», «купить», «не забыть»...\n"
        "💡 *Идея* — «хочу попробовать», «а что если»...\n"
        "📝 *Заметка* — «запомни», «важно», мысли...\n\n"
        "Если не угадаю — появится меню выбора 👇\n\n"
        "*Команды:*\n"
        "/tasks — показать задачи прямо сейчас\n"
        "/help — эта справка\n\n"
        "📬 Каждое утро в 9:00 пришлю сводку по задачам",
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
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO, handle_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("✅ Фунтик запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
