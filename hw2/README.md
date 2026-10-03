
README.md

# GameHub - Redis Backend

Бэкенд для платформы управления игровыми турнирами на базе Redis с использованием Sentinel для отказоустойчивости.

## Архитектура

### Компоненты системы

1. **Redis Master** (порт 6379)

   - Основной узел для операций записи
   - Персистентность: RDB + AOF
   - Защита от split-brain: `min-replicas-to-write 1`
2. **Redis Replicas** (порты 6380, 6381)

   - 2 реплики для операций чтения
   - Режим только для чтения: `replica-read-only yes`
3. **Redis Sentinel** (порты 26379, 26380, 26381)

   - 3 Sentinel процесса для автоматического переключения
   - Кворум: 2
   - Автоматическое обнаружение отказов и failover
4. **Redis Insight** (порт 5540)

   - Веб-интерфейс для мониторинга (опционально)
5. **Flask Application** (порт 5000)

   - REST API сервис
   - Подключение через Sentinel
   - Кэширование, Lua-скрипты, Streams, Pipeline

## Структура данных в Redis

| Тип данных | Ключ              | Описание                      | TTL         |
| ------------------- | --------------------- | ------------------------------------- | ----------- |
| Hash                | `player:{id}`       | Профиль игрока           | ∞          |
| String              | `cache:player:{id}` | Кэш профиля                 | 60 сек   |
| String              | `logins:{id}`       | Счетчик входов           | 24 часа |
| Sorted Set          | `tournament:main`   | Лидерборд                    | ∞          |
| Set                 | `achievements:{id}` | Достижения игрока     | ∞          |
| Stream              | `notifications`     | Очередь уведомлений | 7 дней  |

## Быстрый старт

### 1. Запуск инфраструктуры

```bash
docker compose up -d
```

Проверка статуса:

```bash
docker compose ps
```

Должны быть запущены 6 контейнеров:

- redis-master
- redis-replica-1, redis-replica-2
- sentinel-1, sentinel-2, sentinel-3
- redis-insight (опционально)

### 2. Проверка репликации

```bash
docker compose exec redis-master redis-cli INFO replication | grep connected_slaves
```

Должно показать: `connected_slaves:2`

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 4. Запуск приложения

```bash
python app.py
```

Приложение будет доступно на http://localhost:5000

### 5. Предзаполнение тестовых данных

```bash
python seed_data.py
```

Это создаст все необходимые данные для прохождения автоматической проверки.

### 6. Автоматическая проверка

```bash
python dz1_check.py
```

## API Endpoints

### Профили игроков

**Создать/обновить профиль**

```bash
curl -X POST http://localhost:5000/api/players/1001 \
  -H "Content-Type: application/json" \
  -d '{"name": "Player1", "level": 10, "region": "eu"}'
```

**Получить профиль (с кэшированием)**

```bash
curl http://localhost:5000/api/players/1001
```

**Обновить уровень**

```bash
curl -X PATCH http://localhost:5000/api/players/1001/level \
  -H "Content-Type: application/json" \
  -d '{"delta": 5}'
```

**Зафиксировать вход (Lua-скрипт)**

```bash
curl -X POST http://localhost:5000/api/players/1001/login
```

### Лидерборд

**Добавить/обновить очки**

```bash
curl -X POST http://localhost:5000/api/leaderboard/score \
  -H "Content-Type: application/json" \
  -d '{"player_id": 1001, "score": 100}'
```

**Топ-10 игроков**

```bash
curl http://localhost:5000/api/leaderboard/top?limit=10
```

**Место игрока**

```bash
curl http://localhost:5000/api/leaderboard/rank/1001
```

### Достижения

**Добавить достижение**

```bash
curl -X POST http://localhost:5000/api/players/1001/achievements \
  -H "Content-Type: application/json" \
  -d '{"achievement_name": "first_win"}'
```

**Проверить наличие достижения**

```bash
curl http://localhost:5000/api/players/1001/achievements/first_win
```

**Общие достижения двух игроков**

```bash
curl http://localhost:5000/api/players/1001/achievements/common/1002
```

### Массовые операции

**Массовое создание профилей (Pipeline)**

```bash
curl -X POST http://localhost:5000/api/players/batch \
  -H "Content-Type: application/json" \
  -d '{
    "players": [
      {"id": 2001, "name": "Player1", "level": 5, "region": "eu"},
      {"id": 2002, "name": "Player2", "level": 10, "region": "us"},
      {"id": 2003, "name": "Player3", "level": 15, "region": "asia"}
    ]
  }'
```

## Демонстрация отказоустойчивости

### 1. Проверка Sentinel

```bash
docker compose exec sentinel-1 redis-cli -p 26379 SENTINEL masters
```

### 2. Остановка мастера

```bash
docker stop redis-master
```

Ждем ~15 секунд, затем проверяем:

```bash
docker compose exec sentinel-1 redis-cli -p 26379 SENTINEL get-master-addr-by-name mymaster
```

Sentinel должен показать адрес одной из реплик.

### 3. Проверка работы приложения

Приложение продолжает работать через нового мастера.

### 4. Восстановление мастера

```bash
docker start redis-master
```

Старый мастер автоматически станет репликой нового мастера.

## Демонстрация защиты от split-brain

```bash
# Приостанавливаем все реплики
docker pause redis-replica-1 redis-replica-2

# Пытаемся записать - получим ошибку
curl -X POST http://localhost:5000/api/players/9999 \
  -H "Content-Type: application/json" \
  -d '{"name": "Test"}'

# Восстанавливаем реплики
docker unpause redis-replica-1 redis-replica-2
```

## Кэширование

Первый запрос (cache miss):

```bash
curl http://localhost:5000/api/players/1001
```

Второй запрос (cache hit):

```bash
curl http://localhost:5000/api/players/1001
```

Проверка TTL кэша:

```bash
docker compose exec redis-master redis-cli TTL cache:player:1001
```

## Очередь уведомлений (Streams)

При обновлении уровня игрока автоматически создается уведомление:

```bash
curl -X PATCH http://localhost:5000/api/players/1001/level \
  -H "Content-Type: application/json" \
  -d '{"delta": 5}'
```

Проверка потока:

```bash
docker compose exec redis-master redis-cli XLEN notifications
docker compose exec redis-master redis-cli XRANGE notifications - +
```

Consumer автоматически читает и подтверждает сообщения (XACK).

## Технологии

- **Python 3.10+**
- **Flask 3.0** - веб-фреймворк
- **redis-py 5.0** - клиент Redis с поддержкой Sentinel
- **Redis 7** - хранилище данных
- **Docker Compose** - оркестрация контейнеров

## Особенности реализации

1. **Подключение через Sentinel** - автоматическое обнаружение мастера и реплик
2. **Lua-скрипты** - атомарные операции (счетчик входов с TTL)
3. **Кэширование** - Cache-Aside паттерн с TTL 60 секунд
4. **Streams** - очередь уведомлений с consumer groups
5. **Pipeline** - массовая загрузка данных
6. **Разделение чтения/записи** - запись на мастер, чтение с реплик

## Troubleshooting

### Контейнеры не запускаются

```bash
docker compose down -v
docker compose up -d
```
