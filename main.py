# Standard Library Imports
import os
import sqlite3
from datetime import datetime, timedelta, time
from collections import defaultdict
import threading

# Third-party Imports
from telebot import TeleBot, types  # Telegram Bot API wrapper
from PIL import Image, ImageDraw, ImageFont  # For image confirmation
import pytz  # Timezone support
from dotenv import load_dotenv  # Load Telegram token from .env

# Local Hosting (Replit Keep-Alive)
from keepalive import keep_alive  # Used for Replit + UptimeRobot hosting

# ========== SETUP & INITIALIZATION ========== #

# Load environment variables from .env file (e.g. your bot token)
load_dotenv()

# Initialize the Telegram bot with the token stored in .env
bot = TeleBot(os.getenv('tg_key'))

# Print confirmation in the console
print("Bot token loaded successfully.")

# Set timezone to Singapore
tz = pytz.timezone('Asia/Singapore')

# Start the Flask keep-alive server (for Replit/UptimeRobot)
keep_alive()

# Thread-local storage to handle database access safely
thread_local = threading.local()

# Store session data per user (e.g. name, student ID, current booking)
user_sessions = defaultdict(dict)

# Store temporary available slots per user for inline handling
available_time_slots = {}

# ============================
# DATABASE CONNECTION & SETUP
# ============================

# Connect to SQLite (thread-safe using thread-local storage)
def get_db():
    if not hasattr(thread_local, 'conn'):
        conn = sqlite3.connect('shiftbooktelebot.db', check_same_thread=False)
        conn.row_factory = sqlite3.Row
        thread_local.conn = conn
    return thread_local.conn

# Create necessary tables if they don't exist
def create_tables():
    conn = get_db()
    cursor = conn.cursor()

    # Students table (student_id, name, is_restricted)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            is_restricted INTEGER DEFAULT 0
        )
    ''')

    # Bookings table (id, student_id, shift_date, shift_type, booked_at)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            shift_date TEXT,
            shift_type TEXT,
            booked_at TEXT
        )
    ''')

    conn.commit()

# Call this once when the bot starts to ensure tables exist
create_tables()

# ============================
# BOOKING & LOGIN UTILITIES
# ============================

# Validate student login credentials
def validate_student(student_id, name):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE student_id = ? AND name = ?", (student_id, name))
    return cursor.fetchone()

# Insert new shift booking into the database
def insert_booking(student_id, shift_date, shift_type):
    conn = get_db()
    cursor = conn.cursor()
    booked_at = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO bookings (student_id, shift_date, shift_type, booked_at)
        VALUES (?, ?, ?, ?)
    ''', (student_id, shift_date, shift_type, booked_at))
    conn.commit()

# Get count of bookings in the week of `shift_date`
def get_weekly_booking_count(student_id, shift_date):
    conn = get_db()
    cursor = conn.cursor()
    start_of_week = shift_date - timedelta(days=shift_date.weekday())  # Monday
    end_of_week = start_of_week + timedelta(days=6)  # Sunday
    cursor.execute('''
        SELECT COUNT(*) FROM bookings
        WHERE student_id = ? AND shift_date BETWEEN ? AND ?
    ''', (student_id, start_of_week.isoformat(), end_of_week.isoformat()))
    return cursor.fetchone()[0]

# Get count of bookings in the month of `shift_date`
def get_monthly_booking_count(student_id, shift_date):
    conn = get_db()
    cursor = conn.cursor()
    month_start = shift_date.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    month_end = next_month - timedelta(days=1)
    cursor.execute('''
        SELECT COUNT(*) FROM bookings
        WHERE student_id = ? AND shift_date BETWEEN ? AND ?
    ''', (student_id, month_start.isoformat(), month_end.isoformat()))
    return cursor.fetchone()[0]

# Return True if user can still book shifts on this date (4/week, 10/month unless within 5 days)
def check_shift_limits(student_id, shift_date):
    today = datetime.now(tz).date()
    five_day_limit = today + timedelta(days=5)

    if shift_date <= five_day_limit:
        return True  # Exempted if booking within next 5 days

    weekly = get_weekly_booking_count(student_id, shift_date)
    monthly = get_monthly_booking_count(student_id, shift_date)

    return weekly < 4 and monthly < 10

# ============================
# /start Login Flow
# ============================

@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    user_sessions[chat_id] = {}  # Reset session

    bot.send_message(chat_id, "👋 Welcome to the Student Shift Booking Bot!\nPlease enter your **Student ID**:")
    bot.register_next_step_handler(message, handle_student_id)

def handle_student_id(message):
    chat_id = message.chat.id
    student_id = message.text.strip()
    user_sessions[chat_id]['student_id'] = student_id

    bot.send_message(chat_id, "✅ Now enter your **Full Name** (case-sensitive):")
    bot.register_next_step_handler(message, lambda msg: validate_user(msg, student_id))

def validate_user(message, student_id):
    chat_id = message.chat.id
    name = message.text.strip()

    student = validate_student(student_id, name)

    if student:
        user_sessions[chat_id]['name'] = name
        user_sessions[chat_id]['is_restricted'] = bool(student['is_restricted'])
        user_sessions[chat_id]['pending_bookings'] = []

        bot.send_message(chat_id, f"✅ Login successful! Welcome, *{name}*.", parse_mode='Markdown')
        main_menu = types.ReplyKeyboardMarkup(resize_keyboard=True)
        main_menu.add("/reserve", "/cancel", "/support", "/location")
        bot.send_message(chat_id, "📍 Use the menu below to proceed:", reply_markup=main_menu)

        bot.send_message(chat_id, "📅 Enter the date you want to check for shifts (format: YYYY-MM-DD):")
        bot.register_next_step_handler(message, handle_date_selection)
    else:
        bot.send_message(chat_id, "❌ Invalid Student ID or Name. Please try /start again.")

# ============================
# Shift Selection Flow
# ============================

def handle_date_selection(message):
    chat_id = message.chat.id
    date_str = message.text.strip()

    try:
        shift_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        bot.send_message(chat_id, "⚠ Invalid date format. Please use YYYY-MM-DD.")
        return

    user_sessions[chat_id]['current_date'] = shift_date

    # Load existing bookings from DB
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT shift_type FROM bookings
        WHERE shift_date = ?
    """, (date_str,))
    taken = [row['shift_type'] for row in cursor.fetchall()]
    conn.close()

    # All possible shifts
    all_shifts = ['morning', 'afternoon1', 'afternoon2', 'afternoon3']

    # Allow night shifts only if user is *not* restricted
    if not user_sessions[chat_id].get('is_restricted'):
        all_shifts += ['night1', 'night2']

    # Filter out taken shifts
    available_shifts = [s for s in all_shifts if s not in taken]

    if not available_shifts:
        bot.send_message(chat_id, f"❌ No available shifts on {date_str}. Please choose another date.")
        return

    user_sessions[chat_id]['available_shifts'] = available_shifts

    # Build reply markup for shift selection
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for s in available_shifts:
        markup.add(s)
    markup.add("🔙 Back to Date", "✅ Proceed to Confirm")

    bot.send_message(chat_id, f"🗓 Available shifts on {date_str}:\n\n" +
                     "\n".join(f"• {s}" for s in available_shifts),
                     reply_markup=markup)
    bot.register_next_step_handler(message, handle_shift_selection)

def handle_shift_selection(message):
    chat_id = message.chat.id
    text = message.text.strip().lower()
    session = user_sessions.get(chat_id, {})

    if text == "🔙 back to date":
        bot.send_message(chat_id, "🔁 Enter new date (YYYY-MM-DD):")
        bot.register_next_step_handler(message, handle_date_selection)
        return
    elif text == "✅ proceed to confirm":
        show_booking_summary(chat_id, message)
        return

    shift_type = text
    shift_date = session.get('current_date')

    # Validate shift selection
    if shift_type not in session.get('available_shifts', []):
        bot.send_message(chat_id, "⚠ Invalid shift selection. Please choose from the list.")
        return

    # Restriction: only 1 shift per day for restricted users (either afternoon or night)
    if session.get('is_restricted'):
        already = [b for b in session.get('pending_bookings', []) if b['date'] == shift_date]
        if already:
            bot.send_message(chat_id, "⚠ You can only book *one shift per day* (afternoon or night).", parse_mode='Markdown')
            return

    # Check shift limits (4/week, 10/month unless within 5 days)
    student_id = session.get('student_id')
    if not check_shift_limits(student_id, shift_date):
        bot.send_message(chat_id, "⚠ You’ve reached your shift limit for the week/month. Only bookings within the next 5 days are allowed.")
        return

    # Add this selection to session (pending)
    session.setdefault('pending_bookings', []).append({'date': shift_date, 'shift': shift_type})
    bot.send_message(chat_id, f"✅ Saved: {shift_type} on {shift_date}. You may add more shifts or proceed to confirm.")
    bot.register_next_step_handler(message, handle_shift_selection)

# ============================
# Booking Summary + Confirm
# ============================

def show_booking_summary(chat_id, message):
    bookings = user_sessions[chat_id].get('pending_bookings', [])
    if not bookings:
        bot.send_message(chat_id, "⚠ You haven’t selected any shifts yet.")
        return

    summary = "\n".join([f"• {b['shift']} on {b['date']}" for b in bookings])
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("✅ Confirm All", "❌ Cancel All")

    bot.send_message(chat_id,
                     f"📝 Your pending bookings:\n\n{summary}\n\nWould you like to confirm?",
                     reply_markup=markup)
    bot.register_next_step_handler(message, handle_confirmation)

def handle_confirmation(message):
    chat_id = message.chat.id
    text = message.text.strip()
    session = user_sessions.get(chat_id, {})
    student_id = session.get("student_id")
    bookings = session.get("pending_bookings", [])

    if text == "✅ Confirm All":
        conn = get_db()
        cursor = conn.cursor()

        now_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        for booking in bookings:
            cursor.execute("""
                INSERT INTO bookings (student_id, shift_date, shift_type, booked_at)
                VALUES (?, ?, ?, ?)
            """, (student_id, booking['date'].isoformat(), booking['shift'], now_str))
        conn.commit()
        conn.close()

        summary = "\n".join([f"• {b['shift']} on {b['date']}" for b in bookings])
        bot.send_message(chat_id, f"✅ Your shifts have been booked:\n\n{summary}")
        user_sessions.pop(chat_id, None)  # Clear session after confirmation

    elif text == "❌ Cancel All":
        bot.send_message(chat_id, "❌ All pending bookings have been discarded.")
        session['pending_bookings'] = []

    else:
        bot.send_message(chat_id, "⚠ Invalid option. Please choose Confirm All or Cancel All.")
        show_booking_summary(chat_id, message)

# ============================
# Shift Limit Checks
# (4 per week, 10 per month)
# ============================

def check_shift_limits(student_id, shift_date):
    today = datetime.now(tz).date()
    within_5_days = (shift_date - today).days <= 5
    if within_5_days:
        return True  # allow override

    conn = get_db()
    cursor = conn.cursor()

    # Weekly limit
    start_of_week = shift_date - timedelta(days=shift_date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    cursor.execute("""
        SELECT COUNT(*) FROM bookings
        WHERE student_id = ? AND shift_date BETWEEN ? AND ?
    """, (student_id, start_of_week.isoformat(), end_of_week.isoformat()))
    weekly_count = cursor.fetchone()[0]

    # Monthly limit
    month_start = shift_date.replace(day=1)
    next_month = shift_date.replace(day=28) + timedelta(days=4)
    month_end = (next_month - timedelta(days=next_month.day)).date()
    cursor.execute("""
        SELECT COUNT(*) FROM bookings
        WHERE student_id = ? AND shift_date BETWEEN ? AND ?
    """, (student_id, month_start.isoformat(), month_end.isoformat()))
    monthly_count = cursor.fetchone()[0]

    conn.close()
    return weekly_count < 4 and monthly_count < 10

# ============================
# /reserve Command
# Shortcut to restart booking
# ============================

@bot.message_handler(commands=['reserve'])
def handle_reserve(message):
    chat_id = message.chat.id
    user_sessions[chat_id] = {}  # clear previous session
    bot.send_message(chat_id, "📋 Starting new reservation...\nEnter your Student ID:")
    bot.register_next_step_handler(message, handle_student_id)

# ============================
# /cancel Command
# Remove ALL future bookings
# ============================

@bot.message_handler(commands=['cancel'])
def handle_cancel(message):
    chat_id = message.chat.id
    session = user_sessions.get(chat_id, {})

    student_id = session.get("student_id")
    if not student_id:
        bot.send_message(chat_id, "❌ You are not logged in. Please /start to login.")
        return

    today = datetime.now(tz).date()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM bookings
        WHERE student_id = ? AND shift_date >= ?
    """, (student_id, today.isoformat()))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    if deleted:
        bot.send_message(chat_id, f"✅ All your *future* bookings have been cancelled.", parse_mode="Markdown")
    else:
        bot.send_message(chat_id, "⚠ You don’t have any future bookings to cancel.")

# --------------------------------------------
# Show booking summary & prompt to confirm
# --------------------------------------------
def show_summary(chat_id, message):
    bookings = user_sessions[chat_id].get('pending_bookings', [])
    if not bookings:
        bot.send_message(chat_id, "⚠ You haven't selected any shifts yet.")
        return

    # Create a summary of selected shifts
    summary = "\n".join([f"• {b['shift']} on {b['date']}" for b in bookings])

    # Create confirmation buttons
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Confirm All", "Cancel All")

    bot.send_message(
        chat_id,
        f"📝 *Your pending bookings:*\n\n{summary}\n\nDo you want to confirm?",
        parse_mode="Markdown",
        reply_markup=markup
    )
    bot.register_next_step_handler(message, handle_confirmation)

# ----------------------------------------------------
# Final confirmation handler (insert into database)
# ----------------------------------------------------
def handle_confirmation(message):
    chat_id = message.chat.id
    user_input = message.text.strip()
    session = user_sessions.get(chat_id, {})
    student_id = session.get("student_id")
    bookings = session.get("pending_bookings", [])

    if user_input == "Confirm All":
        if not bookings:
            bot.send_message(chat_id, "⚠ No bookings to confirm.")
            return

        # Open DB connection
        conn = get_db()
        cursor = conn.cursor()
        now_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

        # Insert each confirmed booking
        for booking in bookings:
            cursor.execute("""
                INSERT INTO bookings (student_id, shift_date, shift_type, booked_at)
                VALUES (?, ?, ?, ?)
            """, (student_id, booking['date'].isoformat(), booking['shift'], now_str))

        conn.commit()
        conn.close()

        # Confirmation message
        summary = "\n".join([f"• {b['shift']} on {b['date']}" for b in bookings])
        bot.send_message(chat_id, f"✅ *Your shifts have been booked successfully!*\n\n{summary}", parse_mode="Markdown")

        # Clear session
        user_sessions.pop(chat_id, None)

    elif user_input == "Cancel All":
        # Clear selections without saving
        user_sessions[chat_id]['pending_bookings'] = []
        bot.send_message(chat_id, "❌ All pending bookings have been cancelled.")

    else:
        # Retry prompt
        bot.send_message(chat_id, "Please choose *Confirm All* or *Cancel All*.", parse_mode="Markdown")
        show_summary(chat_id, message)

# --- Location Configuration (Backend editable) ---
# Default location (can be edited in backend)
DEFAULT_LOCATION = "ProjectHub E2 Level 4"

@bot.message_handler(commands=['location'])
def handle_location(message):
    bot.send_message(message.chat.id, f"📍 Project Location:\n{DEFAULT_LOCATION}")


@bot.message_handler(commands=['support'])
def handle_support(message):
    markup = types.InlineKeyboardMarkup()
    markup.row_width = 1
    markup.add(
        types.InlineKeyboardButton("🚨 Emergency Laboratory Safety", callback_data="support_emergency"),
        types.InlineKeyboardButton("🩺 First Aider", callback_data="support_firstaider"),
        types.InlineKeyboardButton("🏥 A&E Unit", callback_data="support_ae"),
        types.InlineKeyboardButton("👩 Admin Support", callback_data="support_admin"),
    )
    bot.send_message(message.chat.id, "Please select a support type:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("support_"))
def handle_support_callback(call):
    support_info = {
        "support_emergency": "🚨 *Emergency Laboratory Safety*\nCall: 9114 8724",
        "support_firstaider": "🩺 *First Aiders Available:*\n- Mr. Francis Ng: 6592 1251\n- Mr. Darryl Lim: 6592 5049",
        "support_ae": "🏥 *Nearest A&E Unit*\nSengkang General Hospital\n110 Sengkang East Way S544886\nContact: 6930 5000",
        "support_admin": "👩 *Admin Support*\nContact Ying: 9370 9168"
    }

    if call.data in support_info:
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, support_info[call.data], parse_mode='Markdown')

if __name__ == "__main__":
    print("Bot is polling for updates...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
