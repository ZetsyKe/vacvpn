FROM python:3.11-slim

# Установка Xray
RUN apt-get update && apt-get install -y wget unzip && rm -rf /var/lib/apt/lists/*
RUN wget https://github.com/XTLS/Xray-core/releases/download/v1.8.4/Xray-linux-64.zip -O /tmp/xray.zip && \
    unzip /tmp/xray.zip -d /tmp/ && \
    chmod +x /tmp/xray && \
    mv /tmp/xray /usr/local/bin/ && \
    mkdir -p /usr/local/etc/xray

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

COPY . .

# Копируем конфиг Xray
COPY config.json /usr/local/etc/xray/config.json

# Создаем скрипт запуска с задержкой
RUN echo '#!/bin/bash\n/usr/local/bin/xray run -config /usr/local/etc/xray/config.json &\nsleep 3\npython main.py' > /app/start.sh && chmod +x /app/start.sh

CMD ["/app/start.sh"]
