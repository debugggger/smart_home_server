# Используем стандартный образ Ubuntu вместо slim версии
FROM python:3.11

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Копирование зависимостей
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY app/ .
COPY kafka_config.py .
COPY sh_utils.py .

CMD ["python", "app_main.py", "--docker"]