#!/usr/bin/env python3
"""
Telegram бот-ассистент Виктории — понимает естественную речь
"""

import os
import subprocess
import logging
import warnings
warnings.filterwarnings('ignore')
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = "8671820769:AAE-Z9aeHvrSyyPNM6ZEAd0OvWzm3gMziuE"
SHEET_URL = "https://docs.google.com/spreadsheets/d/10JPsb1p9z9TrhTQ5IgdIek_mMlxyoeRFE-OTLMZhhus/edit"

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def get_sheet():
    from google.oauth2.service_account import Credentials
    import gspread
    import json
    # Try environment variable first (for Railway), then local file
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if creds_json:
        creds_info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            creds_info,
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
    except Exception as e:
        logger.error(f"Sheet error: {e}")


def classify(text):
    """Определяет что хочет пользователь по ключевым словам"""
    t = text.lower()

    # Команды Mac
    if any(w in t for w in ['открой', 'запусти', 'закрой', 'включи', 'выключи', 'скриншот',
                              'громкость', 'батарея', 'заряд', 'спи', 'спящий', 'ссылка',
                              'вкладк', 'играй', 'пауза', 'время', 'дата']):
        return 'mac'

    # Идеи
    if any(w in t for w in ['идея', 'хочу попробовать', 'а что если', 'было бы круто',
                              'можно было бы', 'думаю запустить', 'хочу создать', 'хочу сделать',
                              'придумала', 'придумал', 'интересно попробовать']):
        return 'idea'

    # Задачи
    if any(w in t for w in ['надо', 'нужно', 'сделать', 'позвонить', 'написать', 'отправить',
                              'встретиться', 'купить', 'оплатить', 'подготовить', 'договориться',
                              'не забыть', 'напомни', 'поставить', 'узнать', 'проверить']):
        return 'task'

    # Заметки
    if any(w in t for w in ['запомни', 'запиши', 'заметка', 'зафиксируй', 'сохрани']):
        return 'note'

    return 'unknown'


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    now = datetime.now().strftime('%d.%m.%Y %H:%M')
    category = classify(text)

    if category == 'mac':
        await handle_mac_command(update, text.lower())

    elif category == 'idea':
        save_to_sheet('Идеи', [now, text, '', '💡 Новая', ''])
        await update.message.reply_text(
            f"💡 Записала идею:\n_{text}_\n\nКогда планируешь внедрить?\n"
            "Ответь: *срочно*, *на неделе*, *в месяце* или *когда-нибудь*",
            parse_mode="Markdown"
        )
        context.user_data['last_idea'] = text
        context.user_data['waiting_deadline'] = True

    elif category == 'task':
        save_to_sheet('Задачи', [now, text, '🆕 Новая', 'Бот'])
        await update.message.reply_text(f"✅ Задача записана:\n_{text}_", parse_mode="Markdown")

    elif category == 'note':
        save_to_sheet('Заметки', [now, text])
        await update.message.reply_text(f"📝 Заметка сохранена:\n_{text}_", parse_mode="Markdown")

    elif context.user_data.get('waiting_deadline'):
        # Ответ на вопрос о сроке идеи
        deadlines = {
            'срочно': (datetime.now() + timedelta(days=2)).strftime('%d.%m.%Y'),
            'на неделе': (datetime.now() + timedelta(days=7)).strftime('%d.%m.%Y'),
            'в месяце': (datetime.now() + timedelta(days=30)).strftime('%d.%m.%Y'),
            'когда-нибудь': 'Без срока',
        }
        t = text.lower()
        for key, deadline in deadlines.items():
            if key in t:
                idea = context.user_data.get('last_idea', '')
                try:
                    ws = get_sheet().worksheet('Идеи')
                    records = ws.get_all_values()
                    for i, row in enumerate(reversed(records)):
                        if idea in row:
                            ws.update_cell(len(records) - i, 5, deadline)
                            break
                except Exception as e:
                    logger.error(e)
                context.user_data['waiting_deadline'] = False
                await update.message.reply_text(f"✅ Срок поставлен: *{deadline}*", parse_mode="Markdown")
                return
        await update.message.reply_text("Напиши: *срочно*, *на неделе*, *в месяце* или *когда-нибудь*", parse_mode="Markdown")

    else:
        # Не понял — сохраняем как заметку
        save_to_sheet('Заметки', [now, text])
        await update.message.reply_text(f"📝 Сохранила как заметку:\n_{text}_", parse_mode="Markdown")


async def handle_mac_command(update, text):
    if 'скриншот' in text:
        path = os.path.expanduser("~/Desktop/screenshot.png")
        subprocess.run(["screencapture", "-x", path])
        with open(path, "rb") as photo:
            await update.message.reply_photo(photo, caption="📸 Готово!")

    elif 'открой' in text or 'запусти' in text:
        app = text.replace('открой', '').replace('запусти', '').strip()
        app_map = {'зум': 'zoom.us', 'zoom': 'zoom.us', 'телеграм': 'Telegram',
                   'хром': 'Google Chrome', 'chrome': 'Google Chrome',
                   'заметки': 'Notes', 'музыка': 'Music', 'spotify': 'Spotify'}
        app_name = app_map.get(app, app)
        result = subprocess.run(["open", "-a", app_name], capture_output=True, text=True)
        if result.returncode == 0:
            await update.message.reply_text(f"✅ Открыла {app_name}!")
        else:
            await update.message.reply_text(f"❌ Не нашла приложение: {app}")

    elif 'громкость' in text:
        nums = [s for s in text.split() if s.isdigit()]
        if nums:
            vol = max(0, min(100, int(nums[0])))
            subprocess.run(["osascript", "-e", f"set volume output volume {vol}"])
            await update.message.reply_text(f"🔊 Громкость: {vol}%")
        else:
            result = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                                    capture_output=True, text=True)
            await update.message.reply_text(f"🔊 Текущая громкость: {result.stdout.strip()}%")

    elif 'батарея' in text or 'заряд' in text:
        result = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True)
        for line in result.stdout.split("\n"):
            if "%" in line:
                await update.message.reply_text(f"🔋 {line.strip()}")
                break

    elif 'время' in text or 'дата' in text:
        await update.message.reply_text(f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}")

    elif 'ссылка' in text:
        result = subprocess.run(
            ["osascript", "-e", 'tell application "Google Chrome" to get URL of active tab of front window'],
            capture_output=True, text=True)
        await update.message.reply_text(f"🌐 {result.stdout.strip()}" if result.returncode == 0 else "❌ Chrome не открыт")

    elif 'все вкладки' in text:
        script = 'tell application "Google Chrome"\nset r to ""\nrepeat with w in windows\nrepeat with t in tabs of w\nset r to r & (title of t) & "\\n"\nend repeat\nend repeat\nreturn r\nend tell'
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        await update.message.reply_text(f"🌐 Открытые вкладки:\n\n{result.stdout.strip()}")

    elif 'спи' in text or 'спящий' in text:
        await update.message.reply_text("😴 Ухожу в сон...")
        subprocess.Popen(["osascript", "-e", 'tell application "System Events" to sleep'])

    elif 'пауза' in text:
        subprocess.run(["osascript", "-e", 'tell application "Music" to pause'])
        await update.message.reply_text("⏸ Пауза")

    elif 'играй' in text:
        subprocess.run(["osascript", "-e", 'tell application "Music" to play'])
        await update.message.reply_text("▶️ Играет!")


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎙 Слушаю...")

    if update.message.voice:
        file = await update.message.voice.get_file()
        ext = "ogg"
    elif update.message.audio:
        file = await update.message.audio.get_file()
        ext = "mp3"
    elif update.message.video:
        file = await update.message.video.get_file()
        ext = "mp4"
    else:
        await update.message.reply_text("❌ Не понял формат")
        return

    path = os.path.expanduser(f"~/telegram_bot/audio_temp.{ext}")
    await file.download_to_drive(path)

    try:
        import whisper
        model = whisper.load_model("base")
        result = model.transcribe(path, language="ru")
        text = result["text"].strip()

        # Classify and save
        now = datetime.now().strftime('%d.%m.%Y %H:%M')
        category = classify(text)

        save_to_sheet('Транскрипции', [now, text, ext])

        if category == 'idea':
            save_to_sheet('Идеи', [now, text, '', '💡 Новая', ''])
            await update.message.reply_text(f"💡 Записала идею:\n_{text}_\n\nКогда внедрить?\nОтветь: срочно / на неделе / в месяце / когда-нибудь", parse_mode="Markdown")
            context.user_data['last_idea'] = text
            context.user_data['waiting_deadline'] = True
        elif category == 'task':
            save_to_sheet('Задачи', [now, text, '🆕 Новая', 'Голосовое'])
            await update.message.reply_text(f"✅ Задача записана:\n_{text}_", parse_mode="Markdown")
        else:
            save_to_sheet('Заметки', [now, text])
            await update.message.reply_text(f"📝 Записала:\n_{text}_", parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
    finally:
        if os.path.exists(path):
            os.remove(path)


async def weekly_review(context):
    try:
        ws = get_sheet().worksheet('Идеи')
        records = ws.get_all_values()[1:]
        new_ideas = [r for r in records if '💡 Новая' in r]
        if not new_ideas:
            return
        text = "🗓 *Обзор идей на неделю*\n\n"
        for i, row in enumerate(new_ideas[:10], 1):
            deadline = row[4] if len(row) > 4 and row[4] else 'без срока'
            text += f"{i}. {row[1]} — _{deadline}_\n"
        text += "\nЧто берёшь в работу? Напиши мне!"
        await context.bot.send_message(chat_id=context.job.chat_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(e)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    context.job_queue.run_daily(weekly_review, time=datetime.strptime("09:00", "%H:%M").time(),
                                 days=(0,), chat_id=chat_id, name=str(chat_id))
    await update.message.reply_text(
        "Привет! Просто пиши или отправляй голосовые — я сама разберусь что сделать:\n\n"
        "💡 Идея → сохраню в трекер идей\n"
        "✅ Задача → запишу в список задач\n"
        "📝 Заметка → сохраню\n"
        "🖥 Команда → выполню на Mac\n\n"
        "Никаких специальных команд не нужно!"
    )


def main():
    import os
    proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    if proxy:
        from telegram.request import HTTPXRequest
        app = Application.builder().token(BOT_TOKEN).request(HTTPXRequest(proxy=proxy)).build()
    else:
        app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE | filters.VIDEO, handle_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("✅ Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
