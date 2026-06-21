FROM python:3.11

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY core/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY core/ .
COPY kafka_config.py .
COPY sh_utils.py .

CMD ["python", "main.py", "--docker"]