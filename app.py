from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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

# Монтирование статических файлов
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    """Главная страница"""
    return {"message": "ZetayKe Bot API", "status": "running"}

@app.get("/health")
async def health_check():
    """Проверка здоровья приложения"""
    return {"status": "healthy", "service": "ZetayKe Bot"}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Загрузка файлов"""
    try:
        # Сохранение файла
        file_location = f"uploads/{file.filename}"
        os.makedirs("uploads", exist_ok=True)
        
        with open(file_location, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        logger.info(f"File {file.filename} uploaded successfully")
        return {"message": "File uploaded successfully", "filename": file.filename}
    
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        reload=os.environ.get("DEBUG", "False").lower() == "true"
    )
