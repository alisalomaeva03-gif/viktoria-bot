#!/usr/bin/env python3
"""
Создаёт и форматирует листы «Заметки» и «Идеи».
Также чинит формулы % в листе «Задачи» (локаль ru_RU — разделитель ;).
"""
import warnings; warnings.filterwarnings('ignore')
import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import gspread
from datetime import datetime

SHEET_ID = "10JPsb1p9z9TrhTQ5IgdIek_mMlxyoeRFE-OTLMZhhus"
CREDS    = os.path.expanduser("~/telegram_bot/google_credentials.json")

creds  = Credentials.from_service_account_file(
    CREDS, scopes=["https://www.googleapis.com/auth/spreadsheets"])
svc    = build("sheets", "v4", credentials=creds)
sheets = svc.spreadsheets()
gc     = gspread.authorize(creds)


# ─── Цвета (те же что в Задачах) ─────────────────────────────────────────────
def c(r, g, b): return {"red": r, "green": g, "blue": b}

WHITE      = c(1.00, 1.00, 1.00)
LIGHT_GRAY = c(0.95, 0.95, 0.96)
MED_GRAY   = c(0.82, 0.82, 0.85)
DARK       = c(0.10, 0.10, 0.15)
HEADER_BG  = c(0.18, 0.34, 0.64)
ALT_ROW    = c(0.94, 0.96, 1.00)

# Цвета статусов идей
IDEA_COLORS = {
    "💡 Новая":          (c(0.98, 0.97, 0.80), c(0.60, 0.50, 0.00)),
    "⚡ В разработке":   (c(0.84, 0.91, 1.00), c(0.17, 0.34, 0.65)),
    "✅ Запущена":       (c(0.82, 0.97, 0.87), c(0.07, 0.45, 0.20)),
    "🗑 Отклонена":      (c(0.93, 0.93, 0.95), c(0.42, 0.42, 0.48)),
}

# Цвета приоритетов идей
PRIO_COLORS = {
    "🔴 Высокий":  (c(1.00, 0.90, 0.90), c(0.75, 0.10, 0.10)),
    "🟡 Средний":  (c(1.00, 0.97, 0.82), c(0.60, 0.45, 0.00)),
    "🟢 Низкий":   (c(0.88, 0.97, 0.90), c(0.07, 0.45, 0.20)),
}

def rgb(col): return {**col}


# ─── API helpers ──────────────────────────────────────────────────────────────
def get_sheet_ids():
    meta = sheets.get(spreadsheetId=SHEET_ID).execute()
    return {s["properties"]["title"]: s["properties"]["sheetId"]
            for s in meta["sheets"]}

def ensure_sheet(name, index=None):
    """Создаёт лист если не существует, возвращает sheetId"""
    existing = get_sheet_ids()
    if name in existing:
        return existing[name]
    req = {"addSheet": {"properties": {"title": name}}}
    if index is not None:
        req["addSheet"]["properties"]["index"] = index
    resp = sheets.batchUpdate(spreadsheetId=SHEET_ID,
                              body={"requests": [req]}).execute()
    return resp["replies"][0]["addSheet"]["properties"]["sheetId"]

def cell_fmt(sid, r0, r1, c0, c1, **fmt):
    return {"repeatCell": {
        "range": {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                  "startColumnIndex": c0, "endColumnIndex": c1},
        "cell": {"userEnteredFormat": fmt},
        "fields": "userEnteredFormat(" + ",".join(fmt.keys()) + ")"}}

def merge(sid, r0, r1, c0, c1):
    return {"mergeCells": {
        "range": {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                  "startColumnIndex": c0, "endColumnIndex": c1},
        "mergeType": "MERGE_ALL"}}

def col_w(sid, col, px):
    return {"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "COLUMNS",
                  "startIndex": col, "endIndex": col + 1},
        "properties": {"pixelSize": px}, "fields": "pixelSize"}}

def row_h(sid, r0, r1, px):
    return {"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS",
                  "startIndex": r0, "endIndex": r1},
        "properties": {"pixelSize": px}, "fields": "pixelSize"}}

def brd(sid, r0, r1, c0, c1, color, w=1):
    b = {"style": "SOLID", "width": w, "color": rgb(color)}
    return {"updateBorders": {
        "range": {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                  "startColumnIndex": c0, "endColumnIndex": c1},
        "top": b, "bottom": b, "left": b, "right": b,
        "innerHorizontal": b, "innerVertical": b}}

def cf_rule(sid, r0, r1, c0, c1, val, bg, fg, idx):
    return {"addConditionalFormatRule": {"rule": {
        "ranges": [{"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                    "startColumnIndex": c0, "endColumnIndex": c1}],
        "booleanRule": {
            "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": val}]},
            "format": {"backgroundColor": rgb(bg),
                       "textFormat": {"foregroundColor": rgb(fg), "bold": True}}
        }}, "index": idx}}

def base_table_format(sid, n_cols, widths, freeze_row=True):
    """Стандартное форматирование таблицы: шапка + чередование + границы + ширины"""
    reqs = []
    reqs += [
        {"unmergeCells": {"range": {"sheetId": sid, "startRowIndex": 0,
            "endRowIndex": 300, "startColumnIndex": 0, "endColumnIndex": 20}}},
        {"appendDimension": {"sheetId": sid, "dimension": "COLUMNS", "length": 10}},
        {"appendDimension": {"sheetId": sid, "dimension": "ROWS",    "length": 300}},
    ]
    # Сброс
    reqs.append(cell_fmt(sid, 0, 300, 0, 20,
        backgroundColor=rgb(WHITE),
        textFormat={"fontFamily": "Arial", "fontSize": 10, "bold": False,
                    "foregroundColor": rgb(DARK)},
        borders={"top": {"style":"NONE"}, "bottom": {"style":"NONE"},
                 "left": {"style":"NONE"}, "right": {"style":"NONE"}}))
    # Шапка
    reqs += [
        cell_fmt(sid, 0, 1, 0, n_cols,
            backgroundColor=rgb(HEADER_BG),
            textFormat={"foregroundColor": rgb(WHITE), "bold": True,
                        "fontSize": 10, "fontFamily": "Arial"},
            horizontalAlignment="CENTER", verticalAlignment="MIDDLE",
            padding={"top": 4, "bottom": 4, "left": 8, "right": 8}),
        row_h(sid, 0, 1, 38),
    ]
    # Чередование
    for r in range(1, 250):
        bg = ALT_ROW if r % 2 == 0 else WHITE
        reqs.append(cell_fmt(sid, r, r+1, 0, n_cols,
            backgroundColor=rgb(bg),
            verticalAlignment="MIDDLE",
            padding={"top": 2, "bottom": 2, "left": 8, "right": 8}))
    reqs.append(row_h(sid, 1, 250, 30))
    reqs.append(brd(sid, 0, 250, 0, n_cols, MED_GRAY))
    for i, w in enumerate(widths):
        reqs.append(col_w(sid, i, w))
    if freeze_row:
        reqs.append({"updateSheetProperties": {
            "properties": {"sheetId": sid,
                           "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}})
    return reqs


# ════════════════════════════════════════════════════════════════════════════
# ЛИСТ «ЗАМЕТКИ»
# Колонки: A=Дата, B=Заметка, C=Категория, D=Источник, E=Тег
# ════════════════════════════════════════════════════════════════════════════
def setup_notes():
    print("📝 Настраиваю лист «Заметки»...")
    sid = ensure_sheet("Заметки", index=1)

    NOTE_W = [110, 420, 130, 110, 120]
    NOTE_H = ["Дата", "Заметка", "Категория", "Источник", "Тег"]

    reqs = base_table_format(sid, 5, NOTE_W)

    # Выравнивание колонки B (Заметка) — перенос текста
    reqs.append(cell_fmt(sid, 1, 250, 1, 2,
        wrapStrategy="WRAP",
        verticalAlignment="TOP",
        padding={"top": 4, "bottom": 4, "left": 8, "right": 8}))

    sheets.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": reqs}).execute()

    # Заголовки
    sheets.values().update(
        spreadsheetId=SHEET_ID, range="Заметки!A1",
        valueInputOption="RAW", body={"values": [NOTE_H]}).execute()

    # Перенести существующие данные если есть в старом листе
    wb = gc.open_by_key(SHEET_ID)
    try:
        existing = wb.worksheet("Заметки")
        rows = [r for r in existing.get_all_values()[1:] if len(r) > 1 and r[1].strip()]
        if rows:
            # Подготавливаем в нужный формат (добавляем пустые колонки если нужно)
            normalized = []
            for r in rows:
                row = [
                    r[0] if len(r) > 0 else "",   # Дата
                    r[1] if len(r) > 1 else "",   # Заметка
                    r[2] if len(r) > 2 else "",   # Категория
                    r[3] if len(r) > 3 else "",   # Источник
                    r[4] if len(r) > 4 else "",   # Тег
                ]
                normalized.append(row)
            sheets.values().update(
                spreadsheetId=SHEET_ID, range="Заметки!A2",
                valueInputOption="RAW", body={"values": normalized}).execute()
            print(f"  ↳ Перенесено {len(normalized)} заметок")
    except Exception:
        pass

    print("  ✅ Лист «Заметки» готов")


# ════════════════════════════════════════════════════════════════════════════
# ЛИСТ «ИДЕИ»
# Колонки: A=Дата, B=Идея, C=Статус, D=Приоритет, E=Срок, F=Заметки
# ════════════════════════════════════════════════════════════════════════════
def setup_ideas():
    print("💡 Настраиваю лист «Идеи»...")
    sid = ensure_sheet("Идеи", index=2)

    IDEA_W  = [110, 360, 145, 130, 110, 220]
    IDEA_H  = ["Дата", "Идея", "Статус", "Приоритет", "Срок", "Заметки"]

    reqs = base_table_format(sid, 6, IDEA_W)

    # Перенос текста в колонках B и F
    for col in [1, 5]:
        reqs.append(cell_fmt(sid, 1, 250, col, col+1,
            wrapStrategy="WRAP",
            verticalAlignment="TOP",
            padding={"top": 4, "bottom": 4, "left": 8, "right": 8}))

    sheets.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": reqs}).execute()

    # Условное форматирование статусов (col C = 2)
    cf_reqs = []
    for idx, (val, (bg, fg)) in enumerate(IDEA_COLORS.items()):
        cf_reqs.append(cf_rule(sid, 1, 250, 2, 3, val, bg, fg, idx))

    # Условное форматирование приоритетов (col D = 3)
    for idx, (val, (bg, fg)) in enumerate(PRIO_COLORS.items()):
        cf_reqs.append(cf_rule(sid, 1, 250, 3, 4, val, bg, fg, idx))

    sheets.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": cf_reqs}).execute()

    # Заголовки
    sheets.values().update(
        spreadsheetId=SHEET_ID, range="Идеи!A1",
        valueInputOption="RAW", body={"values": [IDEA_H]}).execute()

    # Перенести существующие данные
    wb = gc.open_by_key(SHEET_ID)
    try:
        existing = wb.worksheet("Идеи")
        rows = [r for r in existing.get_all_values()[1:] if len(r) > 1 and r[1].strip()]
        if rows:
            normalized = []
            for r in rows:
                # Старый формат: Дата, Идея, [что-то], Статус, Срок
                # Новый формат:  Дата, Идея, Статус, Приоритет, Срок, Заметки
                status = ""
                if len(r) > 3 and r[3]:
                    s = r[3]
                    if "Новая" in s or "💡" in s:
                        status = "💡 Новая"
                    elif "разработ" in s or "⚡" in s:
                        status = "⚡ В разработке"
                    elif "Запущена" in s or "✅" in s:
                        status = "✅ Запущена"
                    elif "Отклонена" in s or "🗑" in s:
                        status = "🗑 Отклонена"
                    else:
                        status = "💡 Новая"

                row = [
                    r[0] if len(r) > 0 else "",   # Дата
                    r[1] if len(r) > 1 else "",   # Идея
                    status or "💡 Новая",          # Статус
                    "🟡 Средний",                  # Приоритет (по умолчанию)
                    r[4] if len(r) > 4 else "",   # Срок
                    r[2] if len(r) > 2 else "",   # Заметки (старый col 3)
                ]
                normalized.append(row)
            sheets.values().update(
                spreadsheetId=SHEET_ID, range="Идеи!A2",
                valueInputOption="RAW", body={"values": normalized}).execute()
            print(f"  ↳ Перенесено {len(normalized)} идей")
    except Exception:
        pass

    print("  ✅ Лист «Идеи» готов")


# ════════════════════════════════════════════════════════════════════════════
# ФИКС ФОРМУЛ % В «ЗАДАЧИ» (локаль ru_RU — разделитель ;)
# ════════════════════════════════════════════════════════════════════════════
def fix_pct_formulas():
    print("🔧 Исправляю формулы % в «Задачи»...")

    # Формула с ; для ru_RU локали
    def pct(row):
        e = f"E{row}"
        return (f'=IF({e}="✅ Готово";100;'
                f'IF({e}="⚡ В работе";50;'
                f'IF({e}="⏸ Отложена";25;0)))')

    vals = [[pct(i)] for i in range(2, 252)]
    sheets.values().update(
        spreadsheetId=SHEET_ID, range="Задачи!F2",
        valueInputOption="USER_ENTERED", body={"values": vals}).execute()

    print("  ✅ Формулы исправлены")


# ════════════════════════════════════════════════════════════════════════════
# ЛИСТ «БАЗА» — файлы, ссылки, фото, документы из бота
# Колонки: A=Дата, B=Тип, C=Название, D=Описание, E=file_id, F=Источник
# ════════════════════════════════════════════════════════════════════════════
def setup_files():
    print("📁 Настраиваю лист «База»...")
    sid = ensure_sheet("База", index=3)

    FILE_W = [110, 100, 260, 260, 200, 140]
    FILE_H = ["Дата", "Тип", "Название", "Описание/Подпись", "file_id", "Источник"]

    reqs = base_table_format(sid, 6, FILE_W)

    # Перенос текста в колонках C и D
    for col in [2, 3]:
        reqs.append(cell_fmt(sid, 1, 250, col, col+1,
            wrapStrategy="WRAP",
            verticalAlignment="TOP",
            padding={"top": 4, "bottom": 4, "left": 8, "right": 8}))

    # Колонка file_id — мелкий шрифт, цвет серый
    reqs.append(cell_fmt(sid, 1, 250, 4, 5,
        textFormat={"fontSize": 8, "foregroundColor": rgb(MED_GRAY)},
        verticalAlignment="MIDDLE"))

    sheets.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": reqs}).execute()

    # Условное форматирование типов
    TYPE_COLORS = {
        "📷 Фото":     (c(0.88, 0.97, 1.00), c(0.10, 0.40, 0.65)),
        "📄 Документ": (c(0.88, 0.94, 1.00), c(0.17, 0.34, 0.65)),
        "🔗 Ссылка":   (c(0.88, 1.00, 0.92), c(0.07, 0.45, 0.20)),
        "🎥 Видео":    (c(1.00, 0.93, 0.88), c(0.65, 0.25, 0.10)),
    }
    cf_reqs = []
    for idx, (val, (bg, fg)) in enumerate(TYPE_COLORS.items()):
        cf_reqs.append(cf_rule(sid, 1, 250, 1, 2, val, bg, fg, idx))
    sheets.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": cf_reqs}).execute()

    # Заголовки
    sheets.values().update(
        spreadsheetId=SHEET_ID, range="База!A1",
        valueInputOption="RAW", body={"values": [FILE_H]}).execute()

    print("  ✅ Лист «База» готов")


# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    fix_pct_formulas()
    setup_notes()
    setup_ideas()
    setup_files()
    print("\n🎉 Готово! Открой Google Sheets — появились листы «Заметки», «Идеи» и «База»")
