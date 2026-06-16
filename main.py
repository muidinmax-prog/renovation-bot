import os
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request

VAPI_API_KEY = os.getenv("VAPI_API_KEY")
VAPI_ASSISTANT_ID = os.getenv("VAPI_ASSISTANT_ID", "40864718-1f1b-4d6d-896f-8b0caf3838bb")
VAPI_SERVER_URL = os.getenv("VAPI_SERVER_URL") # твой реальный Railway-адрес

async def update_vapi_server_url():
    """При старте сервера автоматически прописывает Server URL в ассистенте Alex."""
    if not VAPI_API_KEY:
        print("[Vapi] VAPI_API_KEY не задан — пропускаю обновление.")
        return
    if not VAPI_SERVER_URL:
        print("[Vapi] VAPI_SERVER_URL не задан — пропускаю обновление.")
        return
        
    url = f"https://api.vapi.ai/assistant/{VAPI_ASSISTANT_ID}"
    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"server": {"url": VAPI_SERVER_URL}}
    
    async with httpx.AsyncClient() as client:
        resp = await client.patch(url, headers=headers, json=payload)
        if resp.status_code == 200:
            print(f"[Vapi] ✅ Server URL обновлён: {VAPI_SERVER_URL}")
        else:
            print(f"[Vapi] ❌ Ошибка {resp.status_code}: {resp.text}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await update_vapi_server_url()
    yield

app = FastAPI(lifespan=lifespan)

async def send_telegram(text: str):
    # Считываем актуальные переменные прямо в момент отправки сообщения!
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("OWNER_ID") or os.getenv("CHAT_ID")
    
    if not token or not chat_id:
        print(f"[Telegram] ❌ Ошибка отправки: Проверьте переменные! TOKEN={bool(token)}, CHAT_ID={bool(chat_id)}")
        return
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    print(f"[Telegram] Попытка отправить сообщение чату {chat_id}...")
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        })
        if resp.status_code == 200:
            print("[Telegram] ✅ Сообщение успешно отправлено!")
        else:
            print(f"[Telegram] ❌ Ошибка API {resp.status_code}: {resp.text}")

@app.post("/vapi-webhook")
async def vapi_webhook(request: Request):
    data = await request.json()
    
    # Vapi присылает данные в поле message
    message = data.get("message", {})
    msg_type = message.get("type", "")
    print(f"[Vapi Webhook] Получено событие типа: {msg_type}")
    
    # Обрабатываем только событие окончания звонка
    if msg_type != "end-of-call-report":
        return {"status": "ignored"}
        
    # 1. Извлекаем базовые поля отчета
    analysis = message.get("analysis", {})
    summary = analysis.get("summary", "")
    transcript = message.get("transcript", "")
    ended_reason = message.get("endedReason", "unknown")
    
    # 2. Вытаскиваем системный номер (с которого реально звонили)
    call_data = message.get("call", {})
    phone_caller_id = call_data.get("customer", {}).get("number", "Не определен")
    
    # 3. Вытаскиваем данные, которые ИИ собрал по нашему промту (из блока structuredData)
    structured_data = analysis.get("structuredData", {})
    name = structured_data.get("name", "Не указано")
    city = structured_data.get("city", "Не указан")
    spoken_phone = structured_data.get("spoken_phone", "Клиент не назвал номер")
    
    # Формируем красивое сообщение для Telegram
    lines = [
        "📞 <b>Новый лид обработан ИИ-ассистентом</b>",
        f"👤 <b>Имя клиента:</b> {name}",
        f"🏙 <b>Город проекта:</b> {city}",
        f"📱 <b>Определённый номер (Caller ID):</b> <code>{phone_caller_id}</code>",
        f"🗣 <b>Названный голосом номер:</b> <code>{spoken_phone}</code>",
        f"🚪 <b>Причина завершения:</b> {ended_reason}"
    ]
    
    if summary:
        lines.append(f"\n📝 <b>Краткое содержание:</b>\n{summary}")
    elif transcript:
        # Показываем транскрипт только если нет summary, обрезаем до 3000 символов
        short = transcript[:3000] + ("…" if len(transcript) > 3000 else "")
        lines.append(f"\n📄 <b>Транскрипт:</b>\n{short}")
        
    if not summary and not transcript:
        lines.append("\n⚠️ Нет ни summary, ни транскрипта в отчёте.")
        
    await send_telegram("\n".join(lines))
    return {"status": "ok"}

@app.get("/")
async def health():
    return {"status": "running"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("renovation_bot:app", host="0.0.0.0", port=port)
