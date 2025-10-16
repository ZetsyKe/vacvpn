from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import logging
import asyncio
from datetime import datetime
import threading
import subprocess
import sys  # ДОБАВЬТЕ ЭТУ СТРОКУ

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="VAC VPN Web Server",
    description="Web interface for VAC VPN",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Монтируем статические файлы
os.makedirs("static", exist_ok=True)
if os.path.exists("static") and os.listdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Глобальные переменные для состояния приложения
bot_status = {
    "is_running": False,
    "last_activity": None,
    "errors": []
}

# Функция для запуска бота в отдельном процессе
def run_bot():
    """Запуск бота в отдельном процессе"""
    try:
        logger.info("🤖 Starting Telegram bot in separate process...")
        # Запускаем бот как отдельный процесс
        subprocess.run([sys.executable, "bot.py"], check=True)
    except Exception as e:
        logger.error(f"❌ Bot execution error: {e}")
        bot_status["is_running"] = False
        bot_status["errors"].append(str(e))

@app.on_event("startup")
async def startup_event():
    """Действия при запуске приложения"""
    logger.info("🚀 VAC VPN Web Server starting up...")
    
    # Автоматически запускаем бота при старте
    if not bot_status["is_running"]:
        logger.info("🔄 Starting Telegram bot automatically...")
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        bot_status["is_running"] = True
        bot_status["last_activity"] = datetime.now().isoformat()
        logger.info("✅ Telegram bot started successfully")

@app.get("/")
async def root():
    """Главная страница"""
    # Отдаем index.html
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    
    # Если index.html нет, показываем базовую страницу
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>VAC VPN</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            .status { padding: 10px; margin: 10px 0; border-radius: 5px; }
            .success { background: #d4edda; color: #155724; }
            .warning { background: #fff3cd; color: #856404; }
            .btn { display: inline-block; padding: 10px 20px; margin: 5px; background: #007bff; color: white; text-decoration: none; border-radius: 5px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 VAC VPN Web Server</h1>
            <p>Сервер работает успешно!</p>
            
            <div class="status success">
                <strong>✅ Web Server Status:</strong> ONLINE
            </div>
            
            <div class="status warning">
                <strong>🤖 Bot Status:</strong> RUNNING
            </div>
            
            <div style="margin-top: 20px;">
                <a href="/health" class="btn">Health Check</a>
                <a href="/status" class="btn">System Status</a>
            </div>
        </div>
    </body>
    </html>
    """)

@app.get("/health")
async def health_check():
    """Проверка здоровья системы"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "VAC VPN Web Server",
        "bot": {
            "is_running": bot_status["is_running"]
        }
    }

@app.get("/status")
async def system_status():
    """Полный статус системы"""
    return {
        "status": "operational",
        "timestamp": datetime.now().isoformat(),
        "bot_status": bot_status,
        "environment": "production",
        "web_server": "running"
    }

# Статические файлы
@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/favicon.ico" if os.path.exists("static/favicon.ico") else None)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
