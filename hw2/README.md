
# GameHub - Redis Backend

Бэкенд для платформы управления игровыми турнирами на базе Redis с Sentinel.

## Архитектура

- **Redis Master** (6379) — запись, персистентность RDB + AOF
- **Redis Replicas** (6380, 6381) — чтение, 2 реплики
- **Redis Sentinel** (26379-26381) — автоматический failover, кворум 2
- **Flask API** (5001) — REST API через Sentinel
- **Redis Insight** (5540) — веб-интерфейс (опционально)

## Структура данных

| Тип     | Ключ              | Назначение                   |
| ---------- | --------------------- | -------------------------------------- |
| Hash       | `player:{id}`       | Профиль игрока            |
| String     | `cache:player:{id}` | Кэш профиля (TTL 60с)       |
| String     | `logins:{id}`       | Счётчик входов (TTL 24ч) |
| Sorted Set | `tournament:main`   | Лидерборд                     |
| Set        | `achievements:{id}` | Достижения                   |
| Stream     | `notifications`     | Очередь уведомлений  |

## Быстрый старт

Запуск всех тестов одной командой:

```bash
./run_tests.sh
```

Скрипт автоматически:

- Остановит и удалит старые контейнеры
- Запустит Redis (мастер + 2 реплики + 3 Sentinel)
- Дождётся готовности всех реплик
- Заполнит тестовые данные
- Запустит проверку dz1_check.py
- Остановит контейнеры после завершения

**Флаги:**

- `--no-clean` — пропустить начальную очистку (если контейнеры уже запущены)
- `--keep` — не останавливать контейнеры после тестов

**Примеры:**

```bash
# Полный цикл с очисткой
./run_tests.sh

# Без начальной очистки
./run_tests.sh --no-clean

# Оставить контейнеры работающими
./run_tests.sh --keep

# Комбинация флагов
./run_tests.sh --no-clean --keep
```

## API Endpoints

**Профили:**

```bash
# Создать профиль
curl -X POST http://localhost:5001/api/players/1001 \
  -H "Content-Type: application/json" \
  -d '{"name": "Player1", "level": 10, "region": "eu"}'

# Получить профиль (с кэшированием)
curl http://localhost:5001/api/players/1001

# Зафиксировать вход (Lua-скрипт)
curl -X POST http://localhost:5001/api/players/1001/login
```

**Лидерборд:**

```bash
# Добавить очки
curl -X POST http://localhost:5001/api/leaderboard/score \
  -H "Content-Type: application/json" \
  -d '{"player_id": 1001, "score": 100}'

# Топ-10
curl http://localhost:5001/api/leaderboard/top?limit=10
```

**Достижения:**

```bash
# Добавить достижение
curl -X POST http://localhost:5001/api/players/1001/achievements \
  -H "Content-Type: application/json" \
  -d '{"achievement_name": "first_win"}'

# Общие достижения двух игроков
curl http://localhost:5001/api/players/1001/achievements/common/1002
```

**Массовые операции:**

```bash
# Массовое создание (Pipeline)
curl -X POST http://localhost:5001/api/players/batch \
  -H "Content-Type: application/json" \
  -d '{"players": [{"id": 2001, "name": "P1", "level": 5, "region": "eu"}]}'
```

## Проверка отказоустойчивости

```bash
# Проверка Sentinel
docker compose exec sentinel-1 redis-cli -p 26379 SENTINEL masters

# Остановка мастера
docker stop redis-master

# Проверка нового мастера (через 15 сек)
docker compose exec sentinel-1 redis-cli -p 26379 SENTINEL get-master-addr-by-name mymaster

# Восстановление
docker start redis-master
```

## Проверка защиты от split-brain

```bash
# Приостановка реплик
docker pause redis-replica-1 redis-replica-2

# Попытка записи (должна вернуться ошибка)
curl -X POST http://localhost:5001/api/players/9999 \
  -H "Content-Type: application/json" \
  -d '{"name": "Test"}'

# Восстановление
docker unpause redis-replica-1 redis-replica-2
```
