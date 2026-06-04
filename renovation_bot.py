import telebot
import anthropic
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta

# ─── CONFIG ───────────────────────────────────────────────────────────────────
import os
BOT_TOKEN  = os.environ.get("BOT_TOKEN")
OWNER_ID   = int(os.environ.get("OWNER_ID", "0"))
CLAUDE_KEY = os.environ.get("CLAUDE_KEY")

FOLLOWUP_DELAY_HOURS = 24   # сколько часов ждать перед follow-up
DB_FILE = "leads.db"
# ──────────────────────────────────────────────────────────────────────────────

SYSTEM = """You are Alex, a friendly and professional virtual assistant for Reliable Home Renovation LLC based in Ohio.

Your job is to collect lead information by following these exact steps in order:

STEP 1 — Greeting: Greet the client warmly and ask for their first and last name.
STEP 2 — City: Ask what city the project is located in.
STEP 3 — Phone: Ask for the best phone number to reach them.
STEP 4 — Project: Ask what they would like to renovate or remodel.
STEP 5 — Details: Ask a brief follow-up about the project scope.
STEP 6 — Appointment days: Ask which days work best for a free on-site visit, and if they prefer mornings or afternoons.
STEP 7 — Closing: Thank them warmly and let them know a project manager will contact them soon.

Rules:
- Ask ONE question at a time. Do not skip steps.
- Be warm, concise, and professional.
- Speak in the language the client uses (English or Spanish).
- Never give specific prices.
- When all info is collected, output on its own line:
  LEAD_REPORT:{"name":"...","city":"...","phone":"...","project":"...","details":"...","days":"...","time_pref":"..."}
"""

FOLLOWUP_MSG_EN = (
    "Hi {name}! 👋 This is Alex from Reliable Home Renovation.\n\n"
    "I just wanted to follow up on your interest in {project}. "
    "Our project manager is ready to schedule your FREE on-site estimate! 🏠\n\n"
    "Would you like to confirm your preferred days ({days}) so we can lock in a time? "
    "Just reply here and we'll take care of the rest. 😊"
)

FOLLOWUP_MSG_ES = (
    "¡Hola {name}! 👋 Soy Alex de Reliable Home Renovation.\n\n"
    "Solo quería hacer un seguimiento sobre su interés en {project}. "
    "¡Nuestro gerente de proyectos está listo para programar su estimado GRATIS! 🏠\n\n"
    "¿Le gustaría confirmar sus días preferidos ({days}) para reservar un horario? "
    "Solo responda aquí y nos encargamos del resto. 😊"
)

# ─── DATABASE ─────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER,
            name        TEXT,
            city        TEXT,
            phone       TEXT,
            project     TEXT,
            details     TEXT,
            days        TEXT,
            time_pref   TEXT,
            language    TEXT DEFAULT 'en',
            created_at  TEXT,
            followup_sent INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def save_lead(chat_id, lead: dict, language: str = "en"):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO leads (chat_id, name, city, phone, project, details, days, time_pref, language, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        chat_id,
        lead.get("name", ""),
        lead.get("city", ""),
        lead.get("phone", ""),
        lead.get("project", ""),
        lead.get("details", ""),
        lead.get("days", ""),
        lead.get("time_pref", ""),
        language,
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()
    print(f"[DB] Lead saved: {lead.get('name')} | {lead.get('city')} | {lead.get('phone')}")

def get_pending_followups():
    """Leads that were created >= FOLLOWUP_DELAY_HOURS ago and haven't gotten a follow-up yet."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    cutoff = (datetime.now() - timedelta(hours=FOLLOWUP_DELAY_HOURS)).isoformat()
    c.execute("""
        SELECT id, chat_id, name, project, days, language
        FROM leads
        WHERE followup_sent = 0 AND created_at <= ?
    """, (cutoff,))
    rows = c.fetchall()
    conn.close()
    return rows

def mark_followup_sent(lead_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE leads SET followup_sent = 1 WHERE id = ?", (lead_id,))
    conn.commit()
    conn.close()

# ─── BOT & CLAUDE ─────────────────────────────────────────────────────────────

bot      = telebot.TeleBot(BOT_TOKEN)
ai       = anthropic.Anthropic(api_key=CLAUDE_KEY)
sessions = {}   # chat_id -> list of messages
lang_map = {}   # chat_id -> "en" | "es"

def get_history(chat_id):
    if chat_id not in sessions:
        sessions[chat_id] = []
    return sessions[chat_id]

def detect_language(text: str) -> str:
    """Very simple heuristic: if common Spanish words are present → es."""
    spanish_words = {"hola", "quiero", "necesito", "gracias", "buenos", "por", "favor", "días", "dias"}
    words = set(text.lower().split())
    return "es" if words & spanish_words else "en"

def ask_claude(chat_id, user_text):
    history = get_history(chat_id)
    # Update language detection on every user message
    detected = detect_language(user_text)
    if detected == "es":
        lang_map[chat_id] = "es"
    elif chat_id not in lang_map:
        lang_map[chat_id] = "en"

    history.append({"role": "user", "content": user_text})
    response = ai.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SYSTEM,
        messages=history
    )
    reply = response.content[0].text
    history.append({"role": "assistant", "content": reply})
    return reply

def send_lead_report(lead, chat_id):
    now = datetime.now().strftime("%m/%d/%Y %I:%M %p")
    report = (
        f"📋 *NEW LEAD — Reliable Home Renovation*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {now}\n\n"
        f"👤 *Name:* {lead.get('name','—')}\n"
        f"📍 *City:* {lead.get('city','—')}\n"
        f"📞 *Phone:* {lead.get('phone','—')}\n"
        f"🔨 *Project:* {lead.get('project','—')}\n"
        f"📝 *Details:* {lead.get('details','—')}\n"
        f"📅 *Available days:* {lead.get('days','—')}\n"
        f"🌅 *Preferred time:* {lead.get('time_pref','—')}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 Source: Telegram Bot\n"
        f"🆔 Client chat ID: `{chat_id}`"
    )
    try:
        bot.send_message(OWNER_ID, report, parse_mode="Markdown")
    except Exception as e:
        print(f"[ERROR] Telegram owner notify: {e}")

# ─── FOLLOW-UP SCHEDULER ──────────────────────────────────────────────────────

def followup_worker():
    """Background thread: checks every 30 min for pending follow-ups."""
    print("[Scheduler] Follow-up worker started.")
    while True:
        try:
            pending = get_pending_followups()
            for lead_id, chat_id, name, project, days, language in pending:
                first_name = name.split()[0] if name else "there"
                if language == "es":
                    msg = FOLLOWUP_MSG_ES.format(name=first_name, project=project, days=days)
                else:
                    msg = FOLLOWUP_MSG_EN.format(name=first_name, project=project, days=days)
                try:
                    bot.send_message(chat_id, msg)
                    mark_followup_sent(lead_id)
                    print(f"[Scheduler] Follow-up sent to chat_id={chat_id} ({name})")
                    # Notify owner too
                    bot.send_message(
                        OWNER_ID,
                        f"🔔 *Follow-up sent* to *{name}* (chat `{chat_id}`)\nProject: {project}",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"[Scheduler] Error sending follow-up to {chat_id}: {e}")
        except Exception as e:
            print(f"[Scheduler] Worker error: {e}")
        time.sleep(1800)  # check every 30 minutes

# ─── HANDLERS ─────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "hello"])
def handle_start(message):
    sessions[message.chat.id] = []
    lang_map[message.chat.id] = "en"
    bot.send_message(message.chat.id, ask_claude(message.chat.id, "Hello!"))

@bot.message_handler(commands=["leads"])
def handle_leads(message):
    """Owner-only command: show recent 10 leads."""
    if message.chat.id != OWNER_ID:
        return
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT name, city, phone, project, created_at FROM leads ORDER BY id DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    if not rows:
        bot.send_message(OWNER_ID, "No leads yet.")
        return
    text = "📊 *Last 10 Leads*\n━━━━━━━━━━━━━━━━\n"
    for name, city, phone, project, created_at in rows:
        dt = created_at[:16].replace("T", " ")
        text += f"• *{name}* | {city} | {phone}\n  _{project}_ — {dt}\n\n"
    bot.send_message(OWNER_ID, text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    chat_id = message.chat.id
    reply = ask_claude(chat_id, message.text.strip())
    lead_data = None
    clean_reply = reply
    for line in reply.splitlines():
        if line.strip().startswith("LEAD_REPORT:"):
            try:
                lead_data = json.loads(line.strip()[len("LEAD_REPORT:"):])
                clean_reply = "\n".join(
                    l for l in reply.splitlines() if not l.strip().startswith("LEAD_REPORT:")
                ).strip()
            except Exception as e:
                print(f"[WARN] JSON parse: {e}")
    bot.send_message(chat_id, clean_reply)
    if lead_data:
        language = lang_map.get(chat_id, "en")
        save_lead(chat_id, lead_data, language)
        send_lead_report(lead_data, chat_id)
        sessions[chat_id] = []

# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    # Start follow-up scheduler in background
    t = threading.Thread(target=followup_worker, daemon=True)
    t.start()
    print("✅ Bot is running...")
    bot.infinity_polling()
