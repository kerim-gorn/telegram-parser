# SOCKS к VPS через SSH + autossh (Bot API из Docker Compose)

Telethon ходит в Telegram через **MTProto** (`TELEGRAM_MTPROXY_*`). Бот (ingestor) использует **HTTPS** на `api.telegram.org` — туда **MTProxy не подходит**. Выход: **SOCKS5**, выходящий на интернет **с вашего VPS** (тот же сервер, где telemt).

Сервис **`bot_socks_tunnel`** поднимает внутри Compose **динамический SSH-прокси** (`ssh -D`) и держит его **autossh** (переподключение при обрыве).

## 1. Ключ на VPS

На VPS (под своим пользователем, не root, если так принято):

```bash
# на машине, где будет парсер (или локально):
ssh-keygen -t ed25519 -f ./vps_bot_socks_ed25519 -N ""

# скопировать публичный ключ на VPS
ssh-copy-id -i ./vps_bot_socks_ed25519.pub ВАШ_USER@IP_VPS
```

Проверка без пароля:

```bash
ssh -i ./vps_bot_socks_ed25519 ВАШ_USER@IP_VPS echo ok
```

Приватный ключ положите в репозиторий **нельзя**. Используйте каталог `secrets/` (он в `.gitignore`):

```bash
mkdir -p secrets
mv vps_bot_socks_ed25519 secrets/
chmod 600 secrets/vps_bot_socks_ed25519
```

## 2. Переменные в `.env`

Добавьте (пример):

```env
# Профиль Compose: bot-socks (см. ниже)
VPS_SSH_HOST=89.22.227.231
VPS_SSH_USER=debian
VPS_SSH_PORT=22
BOT_SOCKS_SSH_KEY_FILE=./secrets/vps_bot_socks_ed25519

# Имя сервиса в docker-compose — bot_socks_tunnel
TELEGRAM_BOT_PROXY=socks5://bot_socks_tunnel:1080
```

`TELEGRAM_PROXY` **не задавайте**, если Telethon должен идти только через MTProto.

Первый запуск туннеля добавит VPS в `known_hosts` внутри **тома** `bot_socks_ssh_data` (сохраняется между перезапусками).

## 3. Запуск Compose с туннелем

Туннель вынесен в **профиль** `bot-socks`, чтобы без него стек поднимался как раньше.

```bash
docker compose --profile bot-socks up -d --build
```

Только туннель (отладка):

```bash
docker compose --profile bot-socks logs -f bot_socks_tunnel
```

## 4. Почему туннель не «протухает» надолго

- **OpenSSH**: `ServerAliveInterval=30` и `ServerAliveCountMax=3` — если сеть молчит, ssh шлёт keepalive и рвёт сессию, чтобы **autossh** мог **перезапустить** туннель.
- **autossh**: следит за процессом `ssh` и поднимает его снова после выхода; `AUTOSSH_GATETIME=0` и `AUTOSSH_POLL=60` заданы в `docker-compose.yml`.
- **Docker**: `restart: unless-stopped` у сервиса — контейнер поднимется после ребута хоста.
- **HEALTHCHECK** проверяет, что порт `1080` слушается внутри контейнера.

Полной гарантии при длительном обрыве связи нет, но для типичных NAT/ночных сбросов этого обычно достаточно.

## 5. Проверка

```bash
docker compose --profile bot-socks ps
docker compose --profile bot-socks logs --tail=50 bot_socks_tunnel
```

У `bot_socks_tunnel` в колонке health должен быть `healthy` (через ~40 с после старта).

## 6. Без профиля

```bash
docker compose up -d
```

В этом случае `bot_socks_tunnel` не стартует. Если в `.env` остался `TELEGRAM_BOT_PROXY=socks5://bot_socks_tunnel:1080`, а туннель не запущен, ingestor **не** достучится до бота — очистите `TELEGRAM_BOT_PROXY` или поднимайте профиль `bot-socks`. Схема `socks5h://` в `.env` допустима: в коде она приводится к `socks5://` для aiogram.
