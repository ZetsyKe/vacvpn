from fastapi import FastAPI, UploadFile, File, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import logging
import json
import asyncio
from datetime import datetime
import traceback

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ZetayKe Bot API",
    description="Complete bot application with file processing and management",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Создаем необходимые папки
os.makedirs("uploads", exist_ok=True)
os.makedirs("static", exist_ok=True)
os.makedirs("temp", exist_ok=True)

# Монтируем статические файлы если папка не пустая
if os.path.exists("static") and os.listdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Глобальные переменные для состояния приложения
bot_status = {
    "is_running": False,
    "last_activity": None,
    "active_tasks": 0,
    "errors": []
}

# =============================================================================
# ИМПОРТЫ МОДУЛЕЙ ПРОЕКТА
# =============================================================================

def load_config():
    """Загрузка конфигурации"""
    try:
        if os.path.exists("config.json"):
            with open("config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            logger.warning("config.json not found, using default config")
            return {
                "app_name": "ZetayKe Bot",
                "version": "2.0.0",
                "debug": True
            }
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return {}

def initialize_modules():
    """Инициализация всех модулей проекта"""
    modules_status = {}
    
    try:
        # Пытаемся импортировать бота
        try:
            from bot import main as bot_main, start_bot, stop_bot, process_message
            modules_status["bot"] = {
                "status": "loaded",
                "functions": ["main", "start_bot", "stop_bot", "process_message"]
            }
            bot_modules = {
                "main": bot_main,
                "start_bot": start_bot,
                "stop_bot": stop_bot,
                "process_message": process_message
            }
        except ImportError as e:
            logger.warning(f"Bot module not available: {e}")
            modules_status["bot"] = {"status": "not_available", "error": str(e)}
            bot_modules = None
        
        # Пытаемся импортировать xray_manager
        try:
            from xray_manager import process_xray, analyze_image, generate_report
            modules_status["xray_manager"] = {
                "status": "loaded",
                "functions": ["process_xray", "analyze_image", "generate_report"]
            }
            xray_modules = {
                "process_xray": process_xray,
                "analyze_image": analyze_image,
                "generate_report": generate_report
            }
        except ImportError as e:
            logger.warning(f"XRay manager not available: {e}")
            modules_status["xray_manager"] = {"status": "not_available", "error": str(e)}
            xray_modules = None
        
        return {
            "bot": bot_modules,
            "xray_manager": xray_modules,
            "status": modules_status
        }
    
    except Exception as e:
        logger.error(f"Error initializing modules: {e}")
        return {"bot": None, "xray_manager": None, "status": {}}

# Инициализация при старте
config = load_config()
modules = initialize_modules()

# =============================================================================
# MIDDLEWARE И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Логирование всех запросов"""
    start_time = datetime.now()
    
    response = await call_next(request)
    
    process_time = (datetime.now() - start_time).total_seconds() * 1000
    logger.info(f"{request.method} {request.url.path} - Status: {response.status_code} - {process_time:.2f}ms")
    
    return response

def update_bot_status(is_running: bool = None, error: str = None):
    """Обновление статуса бота"""
    global bot_status
    if is_running is not None:
        bot_status["is_running"] = is_running
    if error:
        bot_status["errors"].append({
            "timestamp": datetime.now().isoformat(),
            "error": error
        })
        # Держим только последние 10 ошибок
        bot_status["errors"] = bot_status["errors"][-10:]
    bot_status["last_activity"] = datetime.now().isoformat()

# =============================================================================
# ОСНОВНЫЕ МАРШРУТЫ
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Главная страница"""
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    else:
        return """
        <!DOCTYPE html>
        <html lang="ru">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>ZetayKe Bot</title>
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body { 
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    padding: 20px;
                }
                .container { 
                    max-width: 1200px; 
                    margin: 0 auto;
                    background: white;
                    border-radius: 15px;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                    overflow: hidden;
                }
                .header {
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 40px 20px;
                    text-align: center;
                }
                .header h1 {
                    font-size: 2.5em;
                    margin-bottom: 10px;
                }
                .header p {
                    font-size: 1.2em;
                    opacity: 0.9;
                }
                .content {
                    padding: 40px;
                }
                .status-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                    gap: 20px;
                    margin-bottom: 40px;
                }
                .status-card {
                    background: #f8f9fa;
                    padding: 25px;
                    border-radius: 10px;
                    border-left: 4px solid #667eea;
                }
                .status-card h3 {
                    color: #333;
                    margin-bottom: 10px;
                }
                .status-card .status {
                    font-weight: bold;
                    padding: 5px 10px;
                    border-radius: 5px;
                    display: inline-block;
                }
                .status.online { background: #d4edda; color: #155724; }
                .status.offline { background: #f8d7da; color: #721c24; }
                .actions {
                    display: flex;
                    gap: 15px;
                    flex-wrap: wrap;
                    margin-bottom: 30px;
                }
                .btn {
                    padding: 12px 25px;
                    border: none;
                    border-radius: 8px;
                    cursor: pointer;
                    font-size: 16px;
                    font-weight: 600;
                    transition: all 0.3s ease;
                    text-decoration: none;
                    display: inline-block;
                }
                .btn-primary {
                    background: #667eea;
                    color: white;
                }
                .btn-secondary {
                    background: #6c757d;
                    color: white;
                }
                .btn-success {
                    background: #28a745;
                    color: white;
                }
                .btn-danger {
                    background: #dc3545;
                    color: white;
                }
                .btn:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 5px 15px rgba(0,0,0,0.2);
                }
                .endpoints {
                    background: #f8f9fa;
                    padding: 25px;
                    border-radius: 10px;
                }
                .endpoints h3 {
                    margin-bottom: 15px;
                }
                .endpoint {
                    background: white;
                    padding: 15px;
                    margin: 10px 0;
                    border-radius: 8px;
                    border-left: 4px solid #28a745;
                }
                .method {
                    font-weight: bold;
                    color: #28a745;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🚀 ZetayKe Bot</h1>
                    <p>Complete AI-powered application with file processing and management</p>
                </div>
                
                <div class="content">
                    <div class="status-grid">
                        <div class="status-card">
                            <h3>API Status</h3>
                            <span class="status online">ONLINE</span>
                            <p>Server is running smoothly</p>
                        </div>
                        <div class="status-card">
                            <h3>Bot Status</h3>
                            <span class="status" id="botStatus">Loading...</span>
                            <p id="botMessage">Checking bot status</p>
                        </div>
                        <div class="status-card">
                            <h3>XRay Manager</h3>
                            <span class="status" id="xrayStatus">Loading...</span>
                            <p id="xrayMessage">Checking XRay status</p>
                        </div>
                        <div class="status-card">
                            <h3>Uploads</h3>
                            <span class="status online">ACTIVE</span>
                            <p id="uploadsCount">Checking files...</p>
                        </div>
                    </div>
                    
                    <div class="actions">
                        <a href="/docs" class="btn btn-primary">API Documentation</a>
                        <a href="/health" class="btn btn-secondary">Health Check</a>
                        <a href="/status" class="btn btn-success">System Status</a>
                        <a href="/files" class="btn btn-primary">File Manager</a>
                    </div>
                    
                    <div class="endpoints">
                        <h3>Available Endpoints</h3>
                        <div class="endpoint">
                            <span class="method">GET</span> /health - System health check
                        </div>
                        <div class="endpoint">
                            <span class="method">POST</span> /upload - Upload files
                        </div>
                        <div class="endpoint">
                            <span class="method">GET</span> /files - List uploaded files
                        </div>
                        <div class="endpoint">
                            <span class="method">POST</span> /bot/start - Start bot
                        </div>
                        <div class="endpoint">
                            <span class="method">POST</span> /bot/stop - Stop bot
                        </div>
                        <div class="endpoint">
                            <span class="method">POST</span> /xray/process - Process XRay images
                        </div>
                    </div>
                </div>
            </div>
            
            <script>
                // Обновление статуса в реальном времени
                async function updateStatus() {
                    try {
                        const response = await fetch('/status');
                        const data = await response.json();
                        
                        // Обновляем статус бота
                        const botStatus = document.getElementById('botStatus');
                        const botMessage = document.getElementById('botMessage');
                        if (data.bot_status.is_running) {
                            botStatus.className = 'status online';
                            botStatus.textContent = 'RUNNING';
                            botMessage.textContent = 'Bot is active';
                        } else {
                            botStatus.className = 'status offline';
                            botStatus.textContent = 'STOPPED';
                            botMessage.textContent = 'Bot is not running';
                        }
                        
                        // Обновляем статус XRay
                        const xrayStatus = document.getElementById('xrayStatus');
                        const xrayMessage = document.getElementById('xrayMessage');
                        if (data.modules_status.xray_manager.status === 'loaded') {
                            xrayStatus.className = 'status online';
                            xrayStatus.textContent = 'READY';
                            xrayMessage.textContent = 'XRay manager loaded';
                        } else {
                            xrayStatus.className = 'status offline';
                            xrayStatus.textContent = 'UNAVAILABLE';
                            xrayMessage.textContent = 'XRay manager not available';
                        }
                        
                        // Обновляем счетчик файлов
                        const uploadsCount = document.getElementById('uploadsCount');
                        uploadsCount.textContent = `${data.uploads_count} files uploaded`;
                        
                    } catch (error) {
                        console.error('Error updating status:', error);
                    }
                }
                
                // Обновляем статус каждые 5 секунд
                updateStatus();
                setInterval(updateStatus, 5000);
            </script>
        </body>
        </html>
        """

@app.get("/health")
async def health_check():
    """Проверка здоровья системы"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "ZetayKe Bot API",
        "version": config.get("version", "2.0.0"),
        "environment": "production",
        "dependencies": {
            "bot_module": modules["status"].get("bot", {}).get("status", "unknown"),
            "xray_module": modules["status"].get("xray_manager", {}).get("status", "unknown"),
            "upload_directory": os.path.exists("uploads"),
            "temp_directory": os.path.exists("temp")
        }
    }
    return health_status

@app.get("/status")
async def system_status():
    """Полный статус системы"""
    uploads_count = len(os.listdir("uploads")) if os.path.exists("uploads") else 0
    
    return {
        "status": "operational",
        "timestamp": datetime.now().isoformat(),
        "bot_status": bot_status,
        "modules_status": modules["status"],
        "uploads_count": uploads_count,
        "system": {
            "python_version": os.sys.version,
            "platform": os.sys.platform,
            "working_directory": os.getcwd()
        }
    }

# =============================================================================
# ФАЙЛОВЫЕ ОПЕРАЦИИ
# =============================================================================

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    """Загрузка файла"""
    try:
        # Проверяем тип файла
        allowed_types = [
            'image/jpeg', 'image/png', 'image/gif', 'image/bmp', 'image/tiff',
            'application/pdf', 'text/plain', 'application/json'
        ]
        
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400, 
                detail=f"File type {file.content_type} not allowed"
            )
        
        # Сохраняем файл
        file_location = f"uploads/{file.filename}"
        with open(file_location, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        logger.info(f"File {file.filename} uploaded successfully ({len(content)} bytes)")
        
        # Если это изображение, запускаем обработку в фоне
        if file.content_type.startswith('image/'):
            background_tasks.add_task(process_uploaded_image, file_location)
        
        return {
            "message": "File uploaded successfully",
            "filename": file.filename,
            "content_type": file.content_type,
            "size": len(content),
            "saved_path": file_location
        }
        
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@app.get("/files")
async def list_files():
    """Список всех загруженных файлов"""
    try:
        files = []
        if os.path.exists("uploads"):
            for filename in os.listdir("uploads"):
                file_path = os.path.join("uploads", filename)
                if os.path.isfile(file_path):
                    stat = os.stat(file_path)
                    files.append({
                        "name": filename,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "path": file_path
                    })
        
        return {
            "files": files,
            "total_count": len(files),
            "total_size": sum(f["size"] for f in files)
        }
    except Exception as e:
        logger.error(f"List files error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list files")

@app.get("/files/{filename}")
async def get_file(filename: str):
    """Получить конкретный файл"""
    try:
        file_path = f"uploads/{filename}"
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found")
        
        return FileResponse(
            file_path,
            filename=filename,
            media_type='application/octet-stream'
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get file error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get file")

# =============================================================================
# БОТ МОДУЛЬ
# =============================================================================

@app.post("/bot/start")
async def start_bot():
    """Запуск бота"""
    try:
        if modules["bot"] is None:
            raise HTTPException(status_code=501, detail="Bot module not available")
        
        if bot_status["is_running"]:
            return {"message": "Bot is already running", "status": "running"}
        
        # Запускаем бота в фоновом режиме
        import threading
        
        def run_bot():
            try:
                if hasattr(modules["bot"]["main"], '__call__'):
                    modules["bot"]["main"]()
                elif hasattr(modules["bot"]["start_bot"], '__call__'):
                    modules["bot"]["start_bot"]()
                update_bot_status(True)
            except Exception as e:
                update_bot_status(False, f"Bot error: {str(e)}")
                logger.error(f"Bot execution error: {e}")
        
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        
        update_bot_status(True)
        logger.info("Bot started successfully")
        
        return {
            "message": "Bot started successfully",
            "status": "running",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        error_msg = f"Failed to start bot: {str(e)}"
        logger.error(error_msg)
        update_bot_status(False, error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@app.post("/bot/stop")
async def stop_bot():
    """Остановка бота"""
    try:
        if modules["bot"] is None:
            raise HTTPException(status_code=501, detail="Bot module not available")
        
        if not bot_status["is_running"]:
            return {"message": "Bot is not running", "status": "stopped"}
        
        # Останавливаем бота
        if hasattr(modules["bot"]["stop_bot"], '__call__'):
            modules["bot"]["stop_bot"]()
        
        update_bot_status(False)
        logger.info("Bot stopped successfully")
        
        return {
            "message": "Bot stopped successfully",
            "status": "stopped",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        error_msg = f"Failed to stop bot: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@app.post("/bot/webhook")
async def bot_webhook(request: Request):
    """Webhook для бота"""
    try:
        data = await request.json()
        
        if modules["bot"] is None:
            raise HTTPException(status_code=501, detail="Bot module not available")
        
        # Обрабатываем сообщение через бот
        if hasattr(modules["bot"]["process_message"], '__call__'):
            result = modules["bot"]["process_message"](data)
        else:
            result = {"status": "received", "data": data}
        
        update_bot_status(True)
        
        return {
            "status": "success",
            "result": result,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        error_msg = f"Webhook error: {str(e)}"
        logger.error(error_msg)
        update_bot_status(False, error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@app.get("/bot/status")
async def get_bot_status():
    """Статус бота"""
    return {
        "bot_status": bot_status,
        "module_available": modules["bot"] is not None,
        "timestamp": datetime.now().isoformat()
    }

# =============================================================================
# XRAY МОДУЛЬ
# =============================================================================

@app.post("/xray/process")
async def process_xray_image(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    """Обработка XRay изображения"""
    try:
        if modules["xray_manager"] is None:
            raise HTTPException(status_code=501, detail="XRay manager not available")
        
        # Проверяем что это изображение
        if not file.content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="File must be an image")
        
        # Сохраняем временный файл
        temp_path = f"temp/{file.filename}"
        with open(temp_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # Обрабатываем изображение
        if hasattr(modules["xray_manager"]["process_xray"], '__call__'):
            result = modules["xray_manager"]["process_xray"](temp_path)
        elif hasattr(modules["xray_manager"]["analyze_image"], '__call__'):
            result = modules["xray_manager"]["analyze_image"](temp_path)
        else:
            result = {"status": "processed", "filename": file.filename}
        
        # Удаляем временный файл
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        logger.info(f"XRay image {file.filename} processed successfully")
        
        return {
            "status": "success",
            "result": result,
            "filename": file.filename,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"XRay processing error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"XRay processing failed: {str(e)}")

@app.post("/xray/analyze")
async def analyze_xray_image(file: UploadFile = File(...)):
    """Анализ XRay изображения"""
    try:
        if modules["xray_manager"] is None:
            raise HTTPException(status_code=501, detail="XRay manager not available")
        
        if not file.content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="File must be an image")
        
        # Сохраняем временный файл
        temp_path = f"temp/{file.filename}"
        with open(temp_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # Анализируем изображение
        if hasattr(modules["xray_manager"]["analyze_image"], '__call__'):
            analysis_result = modules["xray_manager"]["analyze_image"](temp_path)
        else:
            analysis_result = {
                "analysis": "basic_analysis",
                "findings": [],
                "confidence": 0.95,
                "filename": file.filename
            }
        
        # Генерируем отчет если доступно
        if hasattr(modules["xray_manager"]["generate_report"], '__call__'):
            report = modules["xray_manager"]["generate_report"](analysis_result)
        else:
            report = {"summary": "Analysis completed", "details": analysis_result}
        
        # Удаляем временный файл
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        return {
            "status": "success",
            "analysis": analysis_result,
            "report": report,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"XRay analysis error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"XRay analysis failed: {str(e)}")

# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

async def process_uploaded_image(file_path: str):
    """Фоновая обработка загруженного изображения"""
    try:
        logger.info(f"Background processing image: {file_path}")
        
        # Здесь может быть любая логика обработки изображений
        # Например, сжатие, анализ, классификация и т.д.
        
        await asyncio.sleep(1)  # Имитация обработки
        logger.info(f"Background processing completed for: {file_path}")
        
    except Exception as e:
        logger.error(f"Background processing error for {file_path}: {e}")

@app.on_event("startup")
async def startup_event():
    """Действия при запуске приложения"""
    logger.info("🚀 ZetayKe Bot API starting up...")
    logger.info(f"📁 Working directory: {os.getcwd()}")
    logger.info(f"🔧 Loaded modules: {modules['status']}")
    logger.info("✅ Application startup completed")

@app.on_event("shutdown")
async def shutdown_event():
    """Действия при остановке приложения"""
    logger.info("🛑 ZetayKe Bot API shutting down...")
    
    # Останавливаем бота при завершении работы
    if bot_status["is_running"] and modules["bot"] is not None:
        try:
            if hasattr(modules["bot"]["stop_bot"], '__call__'):
                modules["bot"]["stop_bot"]()
            logger.info("✅ Bot stopped gracefully")
        except Exception as e:
            logger.error(f"❌ Error stopping bot: {e}")

# =============================================================================
# ЗАПУСК ПРИЛОЖЕНИЯ
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    debug = os.environ.get("DEBUG", "False").lower() == "true"
    
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        reload=debug,
        log_level="info",
        access_log=True
    )
