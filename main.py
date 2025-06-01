import logging
import datetime
import json
import os
import pytz
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATA_FILE = "data.json"
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

logging.basicConfig(level=logging.INFO)

def load_bookings():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_bookings(bookings):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(bookings, f, ensure_ascii=False, indent=2)

def get_available_dates():
    now = datetime.datetime.now(MOSCOW_TZ)
    dates = []
    for i in range(14):
        day = now + datetime.timedelta(days=i)
        if day.weekday() < 5:
            dates.append(day.date())
    return dates

def get_available_slots(date, duration):
    start_times = [(10, 0), (11, 0), (12, 0), (14, 0), (15, 0), (16, 0)]
    if duration == 2:
        start_times = [(10, 0), (11, 0), (14, 0), (15, 0)]
    elif duration == 3 or duration == 4:
        start_times = [(10, 0), (14, 0)]
    bookings = load_bookings()
    booked_slots = [
        (datetime.datetime.fromisoformat(b["start"]), datetime.datetime.fromisoformat(b["end"]))
        for b in bookings if datetime.date.fromisoformat(b["date"]) == date
    ]
    slots = []
    now = datetime.datetime.now(MOSCOW_TZ) + datetime.timedelta(hours=1)
    for hour, minute in start_times:
        start = datetime.datetime.combine(date, datetime.time(hour, minute), tzinfo=MOSCOW_TZ)
        end = start + datetime.timedelta(hours=duration)
        if all(end <= s or start >= e for s, e in booked_slots) and start > now:
            slots.append((start, end))
    return slots

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Начать бронирование", callback_data="start_booking")],
        [InlineKeyboardButton("Мои бронирования", callback_data="view_bookings")]
    ]
    await update.message.reply_text("Выберите действие:", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_bookings(update_or_query, context: ContextTypes.DEFAULT_TYPE, as_query=False):
    user_id = update_or_query.from_user.id
    bookings = load_bookings()
    user_bookings = [
        b for b in bookings if b["user_id"] == user_id and
        datetime.datetime.fromisoformat(b["end"]) > datetime.datetime.now(MOSCOW_TZ)
    ]
    if not user_bookings:
        text = "У вас нет запланированного времени работ."
    else:
        text = "Ваши бронирования:\n\n"
        for b in user_bookings:
            start = datetime.datetime.fromisoformat(b["start"])
            end = datetime.datetime.fromisoformat(b["end"])
            text += f"✅ {start.strftime('%d.%m %H:%M')} – {end.strftime('%H:%M')}\n"

    if as_query:
        await update_or_query.edit_message_text(text)
    else:
        await update_or_query.message.reply_text(text)

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "start_booking":
        keyboard = [
            [InlineKeyboardButton("1 час", callback_data="duration_1")],
            [InlineKeyboardButton("2 часа", callback_data="duration_2")],
            [InlineKeyboardButton("3 часа", callback_data="duration_3")],
            [InlineKeyboardButton("4 часа", callback_data="duration_4")]
        ]
        await query.edit_message_text("Выберите длительность:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "view_bookings":
        await show_bookings(query, context, as_query=True)

    elif data.startswith("duration_"):
        hours = int(data.split("_")[1])
        context.user_data["duration"] = hours
        dates = get_available_dates()
        keyboard = [
            [InlineKeyboardButton(date.strftime("%d.%m.%Y (%A)"), callback_data=f"date_{date}")]
            for date in dates
        ]
        await query.edit_message_text("Выберите дату:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("date_"):
        date = datetime.date.fromisoformat(data.split("_")[1])
        context.user_data["date"] = date
        duration = context.user_data.get("duration", 1)
        slots = get_available_slots(date, duration)
        if not slots:
            await query.edit_message_text("На выбранную дату нет доступного времени.")
            return
        buttons = []
        for start, end in slots:
            label = f"{start.strftime('%H:%M')} – {end.strftime('%H:%M')}"
            cb = f"book_{start.isoformat()}_{end.isoformat()}"
            buttons.append([InlineKeyboardButton(label, callback_data=cb)])
        await query.edit_message_text("Выберите время:", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("book_"):
        _, start_str, end_str = data.split("_", 2)
        start = datetime.datetime.fromisoformat(start_str)
        end = datetime.datetime.fromisoformat(end_str)
        user_id = query.from_user.id
        bookings = load_bookings()
        if any(b["start"] == start_str for b in bookings):
            await query.edit_message_text("Это время уже занято.")
            return
        bookings.append({
            "user_id": user_id,
            "date": start.date().isoformat(),
            "start": start_str,
            "end": end_str
        })
        save_bookings(bookings)
        await query.edit_message_text(
            "Вы успешно забронировали время! Пожалуйста, напишите мне в телеграм https://t.me/kolbeshev "
            "или на почту design@kolbeshev.ru описание вашей задачи (ТЗ) и мы обсудим её более детально."
        )
        if ADMIN_ID:
            await context.bot.send_message(chat_id=ADMIN_ID,
                text=f"Новое бронирование от пользователя {user_id} на {start.strftime('%d.%m %H:%M')} – {end.strftime('%H:%M')}.")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    print("✅ Бот запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()