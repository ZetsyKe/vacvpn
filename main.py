from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os
from dotenv import load_dotenv
from payment import create_payment

load_dotenv("backend/key.env")  # путь к .env

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent

@app.get("/", response_class=HTMLResponse)
async def read_index():
    return FileResponse(BASE_DIR / "index.html")

@app.post("/create-payment")
async def payment_endpoint(request: Request):
    data = await request.json()
    amount = data.get("amount", 100)  # сумма по умолчанию — 100
    payment_url = create_payment(amount)
    return {"payment_url": payment_url}