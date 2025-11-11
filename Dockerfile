# Python 3.11+ базовый образ
FROM python:3.11-slim

# Метаданные образа
LABEL maintainer="parser-llm-team"
LABEL description="Parser-LLM Telegram Parser Service"

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Создание рабочей директории
WORKDIR /app

# Копирование файла зависимостей
COPY requirements.txt .

# Установка Python зависимостей
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода приложения
COPY . .

# Создание непривилегированного пользователя
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# Переключение на непривилегированного пользователя
USER appuser

# Переменная окружения для Python (отключение буферизации)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Healthcheck (будет переопределен в docker-compose для разных сервисов)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "print('healthy')" || exit 1

# Команда по умолчанию (будет переопределена в docker-compose)
CMD ["python", "-m", "src.main"]
