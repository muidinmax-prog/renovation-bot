import telebot
import anthropic
import json
from datetime import datetime

BOT_TOKEN = "8880432154:AAGIu9EE3zzIOplTTAcj3XL_WGxKQvId0ZE"
OWNER_ID = 7235430104
CLAUDE_KEY = "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"

SYSTEM = """You are Alex, a friendly and professional virtual assistant for Reliable Home Renovation LLC based in Ohio. Your job is to collect lead information by following these exact steps in order: STEP 1 — Greeting: Greet the client warmly and ask for their first and last name. STEP 2 — City: Ask what city the project is located in. STEP 3 — Phone: Ask for the best phone number to reach them. STEP 4 — Project: Ask what they would like to renovate or remodel. STEP 5 — Details: Ask a brief follow-up about the project scope. STEP 6 — Appointment days: Ask which days work best for a free on-site visit, and if they prefer mornings or afternoons. STEP 7 — Closing: Thank them warmly and let them know a project manager will contact them soon. Rules: - Ask ONE question at a time. Do not skip steps. - Be warm, concise, and professional. - Speak in the language the client uses (English or Spanish). - Never give specific prices. - When all info is collected, output on its own line: LEAD_REPORT:{"name":"...","city":"...","phone":"...","project":"...","details":"...","days":"...","time_pref":"..."} """

bot = telebot.TeleBot("8880432154:AAGIu9EE3zzIOplTTAcj3XL_WGxKQvId0ZE")
ai = anthropic.Anthropic(api_key=CLAUDE_KEY)
sessions = {}

def get_history(chat_id):
    if chat_id not in sessions:
        sessions[chat_id] = []
    return sessions[chat_id]

def ask_claude(chat_id, user_text):
    history = get_history(chat_id)
    history.append({"role": "user", "content": user_text})
    response = ai.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1000,
        system=SYSTEM,
        messages=history
    )
    reply = response.content.text
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
        print(f"[ERROR] {e}")

@bot.message_handler(commands=["start","hello"])
def handle_start(message):
    sessions[message.chat.id] = []
    bot.send_message(message.chat.id, ask_claude(message.chat.id, "Hello!"))

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
                clean_reply = "\n".join(l for l in reply.splitlines() if not l.strip().startswith("LEAD_REPORT:")).strip()
            except Exception as e:
                print(f"[WARN] {e}")
    bot.send_message(chat_id, clean_reply)
    if lead_data:
        send_lead_report(lead_data, chat_id)
        sessions[chat_id] = []

if __name__ == "__main__":
    print("✅ Bot is running...")
    bot.infinity_polling()
