import os
import asyncio
import subprocess
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_command(command, service_name):
    """Запускает команду и логирует вывод"""
    logger.info(f"🚀 Starting {service_name}...")
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Логируем вывод в реальном времени
    async def log_stream(stream, stream_type):
        while True:
            line = await stream.readline()
            if not line:
                break
            logger.info(f"[{service_name}] {line.decode().strip()}")
    
    await asyncio.gather(
        log_stream(process.stdout, "STDOUT"),
        log_stream(process.stderr, "STDERR")
    )
    
    return await process.wait()

async def main():
    """Запускает все сервисы"""
    # Запускаем API
    api_task = asyncio.create_task(
        run_command([
            "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"
        ], "API")
    )
    
    # Запускаем бота
    bot_task = asyncio.create_task(
        run_command(["python", "bot.py"], "BOT")
    )
    
    # Ждем завершения
    await asyncio.gather(api_task, bot_task)

if __name__ == "__main__":
    logger.info("🎯 Starting VAC VPN services...")
    asyncio.run(main())
