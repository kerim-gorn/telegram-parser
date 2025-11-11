# Parser-LLM

Telegram парсер на основе Producer-Queue-Consumer архитектуры с использованием Telethon, Celery и RabbitMQ.

## 🏗️ Архитектура

Проект использует микросервисную архитектуру с разделением на два типа воркеров:

1. **Historical Worker (Celery)** - эфемерный воркер для парсинга истории чатов
2. **Real-time Worker (Persistent)** - постоянно работающий сервис для мониторинга новых сообщений

## 🛠️ Технологический стек

- **Python 3.11+** с asyncio
- **Telethon** для работы с Telegram API
- **PostgreSQL** для хранения данных
- **Redis** для хранения сессий и кеширования
- **RabbitMQ** как message broker
- **Celery** для обработки задач
- **Docker Compose** для оркестрации

## 🚀 Быстрый старт

### 1. Клонирование репозитория

```bash
git clone <repository-url>
cd parser-llm
```

### 2. Настройка окружения

Скопируйте `.env.example` в `.env` и заполните необходимые переменные:

```bash
cp .env.example .env
nano .env  # или используйте любой редактор
```

**Обязательные переменные:**
- `TELEGRAM_API_ID` - получить на https://my.telegram.org/apps
- `TELEGRAM_API_HASH` - получить на https://my.telegram.org/apps
- `TELEGRAM_PHONE` - номер телефона в международном формате
- Измените пароли для БД, Redis и RabbitMQ

### 3. Запуск сервисов

```bash
# Запуск всех сервисов
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка сервисов
docker-compose down
```

### 4. Применение миграций БД

```bash
# Выполнение миграций
docker-compose exec historical-worker alembic upgrade head
```

## 📁 Структура проекта

```
parser-llm/
├── src/
│   ├── db/              # Модели БД и подключения
│   ├── telegram_client/ # Клиент Telegram (Telethon)
│   ├── workers/         # Celery и Real-time воркеры
│   ├── settings/        # Конфигурация приложения
│   └── utils/           # Утилиты и хелперы
├── alembic/             # Миграции БД
├── tests/               # Тесты
├── docker-compose.yml   # Конфигурация Docker
├── Dockerfile           # Образ приложения
├── requirements.txt     # Python зависимости
└── .env.example         # Пример переменных окружения
```

## 🔧 Разработка

### Локальная разработка

```bash
# Создание виртуального окружения
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows

# Установка зависимостей
pip install -r requirements.txt
```

### Создание миграций

```bash
# Создание новой миграции
docker-compose exec historical-worker alembic revision --autogenerate -m "описание изменений"

# Применение миграции
docker-compose exec historical-worker alembic upgrade head

# Откат миграции
docker-compose exec historical-worker alembic downgrade -1
```

## 🔐 Безопасность

- ❌ **НИКОГДА** не коммитьте `.env` файл
- ❌ **НИКОГДА** не храните `*.session` файлы (мы используем StringSession в Redis)
- ✅ Используйте сильные пароли для всех сервисов
- ✅ Шифруйте StringSession с помощью `SESSION_ENCRYPTION_KEY`

## 📊 Мониторинг

- **RabbitMQ Management UI**: http://localhost:15672 (user/pass из .env)
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379

## 🐛 Troubleshooting

### Проблемы с подключением к Telegram

Убедитесь, что:
1. API_ID и API_HASH корректны
2. Номер телефона в международном формате (+...)
3. StringSession корректно сохранен в Redis

### Ошибки FloodWait

Проект имеет встроенную защиту от FloodWait. Настройте параметры в `.env`:
- `FLOOD_WAIT_MAX_DELAY`
- `MIN_REQUEST_DELAY`
- `MAX_REQUEST_DELAY`

## 📝 Лицензия

[Укажите вашу лицензию]

## 🤝 Вклад в проект

[Правила контрибуции]
