FROM python:3.11-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Установка Xray
RUN wget https://github.com/XTLS/Xray-core/releases/download/v1.8.4/Xray-linux-64.zip -O /tmp/xray.zip \
    && unzip /tmp/xray.zip -d /tmp/ \
    && chmod +x /tmp/xray \
    && mv /tmp/xray /usr/local/bin/ \
    && mkdir -p /usr/local/etc/xray \
    && rm /tmp/xray.zip

WORKDIR /app

# Копируем и устанавливаем Python зависимости
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Копируем исходный код
COPY . .

# Копируем конфиг Xray
COPY config.json /usr/local/etc/xray/config.json

# Создаем скрипт запуска
RUN echo '#!/bin/bash\n\necho "Starting Xray..."\n/usr/local/bin/xray run -config /usr/local/etc/xray/config.json &\n\necho "Starting FastAPI..."\npython main.py\n' > /app/start.sh \
    && chmod +x /app/start.sh

# Запускаем через скрипт
CMD ["/app/start.sh"]
