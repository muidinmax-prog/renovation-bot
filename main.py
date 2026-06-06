import os
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_API_URL   = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

VAPI_API_KEY        = os.getenv("VAPI_API_KEY")
VAPI_ASSISTANT_ID   = os.getenv("VAPI_ASSISTANT_ID", "40864718-1f1b-4d6d-896f-8b0caf3838bb")
VAPI_SERVER_URL     = os.getenv("VAPI_SERVER_URL")   # твой реальный Railway-адрес


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
    async with httpx.AsyncClient() as client:
        await client.post(TELEGRAM_API_URL, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        })


@app.post("/vapi-webhook")
async def vapi_webhook(request: Request):
    data = await request.json()

    # Vapi присылает данные в поле message
    message = data.get("message", {})
    msg_type = message.get("type", "")

    # Обрабатываем только событие окончания звонка
    if msg_type != "end-of-call-report":
        return {"status": "ignored"}

    # Извлекаем нужные поля
    summary = message.get("summary", "")
    transcript = message.get("transcript", "")
    ended_reason = message.get("endedReason", "unknown")

    # Формируем сообщение для Telegram
    lines = [f"📞 <b>Звонок завершён</b> — причина: <code>{ended_reason}</code>"]

    if summary:
        lines.append(f"\n📝 <b>Краткое содержание:</b>\n{summary}")

    if transcript and not summary:
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
    uvicorn.run("main:app", host="0.0.0.0", port=port)
