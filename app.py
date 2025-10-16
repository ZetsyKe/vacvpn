from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
import uvicorn
import os
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ZetayKe Bot", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Создаем необходимые папки если их нет
os.makedirs("uploads", exist_ok=True)
# Не монтируем static папку, если её нет

@app.get("/", response_class=HTMLResponse)
async def root():
    """Главная страница"""
    # Проверяем существует ли index.html
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    else:
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>ZetayKe Bot</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                .container { max-width: 800px; margin: 0 auto; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🚀 ZetayKe Bot API</h1>
                <p>Сервер работает корректно!</p>
                <ul>
                    <li><a href="/docs">API Documentation</a></li>
                    <li><a href="/health">Health Check</a></li>
                </ul>
            </div>
        </body>
        </html>
        """

@app.get("/health")
async def health_check():
    """Проверка здоровья приложения"""
    return {
        "status": "healthy", 
        "service": "ZetayKe Bot",
        "timestamp": "2024-01-01T00:00:00Z"  # Добавьте реальную временную метку
    }

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Загрузка файлов"""
    try:
        # Создаем папку uploads если её нет
        os.makedirs("uploads", exist_ok=True)
        
        # Сохранение файла
        file_location = f"uploads/{file.filename}"
        
        with open(file_location, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        logger.info(f"File {file.filename} uploaded successfully")
        return {
            "message": "File uploaded successfully", 
            "filename": file.filename,
            "size": len(content)
        }
    
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/files")
async def list_files():
    """Список загруженных файлов"""
    try:
        if os.path.exists("uploads"):
            files = os.listdir("uploads")
            return {"files": files}
        else:
            return {"files": []}
    except Exception as e:
        logger.error(f"List files error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Добавьте здесь импорт и маршруты для вашего бота
# from bot import your_bot_function

@app.post("/bot/webhook")
async def bot_webhook(data: dict):
    """Webhook для бота"""
    try:
        # result = await your_bot_function(data)
        return {
            "status": "success", 
            "message": "Bot webhook received",
            "data": data
        }
    except Exception as e:
        logger.error(f"Bot error: {str(e)}")
        raise HTTPException(status_code=500, detail="Bot processing error")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        reload=os.environ.get("DEBUG", "False").lower() == "true"
    )
