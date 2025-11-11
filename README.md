# Parser-LLM Project

Проект для парсинга сообщений из Telegram с использованием архитектуры "Продюсер-Очередь-Консьюмер".

## Технологический стек

- **Python 3.11+** (asyncio)
- **Telethon** для работы с Telegram API
- **Docker Compose** для оркестрации
- **RabbitMQ** как брокер сообщений
- **Celery** для задач и воркеров
- **Redis** для хранения сессий
- **PostgreSQL** для хранения данных (SQLAlchemy + Alembic)

## Быстрый старт

1. Скопируйте `.env.example` в `.env` и заполните необходимые переменные:
   ```bash
   cp .env.example .env
   ```

2. Запустите сервисы:
   ```bash
   docker-compose up -d
   ```

3. Сервисы будут доступны:
   - PostgreSQL: `localhost:5432`
   - RabbitMQ Management: `http://localhost:15672`
   - Redis: `localhost:6379`

## Структура проекта

```
.
├── src/                    # Исходный код приложения
│   ├── db/                # Модуль работы с БД
│   ├── telegram_client/   # Клиент Telegram (Telethon)
│   ├── workers/           # Воркеры (Celery и Real-time)
│   └── settings/          # Конфигурация
├── alembic/               # Миграции БД
├── docker-compose.yml     # Конфигурация Docker Compose
├── Dockerfile             # Образ для приложения
├── requirements.txt       # Python зависимости
└── .env.example           # Пример переменных окружения
```

## Архитектура

Проект использует паттерн "Продюсер-Очередь-Консьюмер" с двумя типами воркеров:

1. **Исторический Воркер (Celery Worker)**: Эфемерный воркер, который получает задачи из RabbitMQ, парсит историю чатов и сохраняет данные в БД.

2. **Real-time Воркер (Persistent Service)**: Постоянно запущенный сервис, который слушает новые сообщения через `events.NewMessage` и отправляет их в RabbitMQ для обработки.

Сессии Telegram хранятся в Redis в виде зашифрованных StringSession (stateless подход).
