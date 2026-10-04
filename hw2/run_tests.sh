#!/bin/bash
set -e

# Флаги
CLEAN=true
KEEP_RUNNING=false

for arg in "$@"; do
    case $arg in
        --no-clean) CLEAN=false ;;
        --keep) KEEP_RUNNING=true ;;
    esac
done

echo ""
echo "GameHub — запуск и тестирование"
echo ""

# ── Шаг 1: Очистка ────────────────────────────────────────

if [ "$CLEAN" = true ]; then
    echo "[1/5] Очистка предыдущего состояния..."
    docker compose down -v --remove-orphans
    echo "  OK: Контейнеры и volumes удалены"
else
    echo "[1/5] Пропуск очистки (--no-clean)"
fi
echo ""

# ── Шаг 2: Запуск Docker Compose ──────────────────────────

echo "[2/5] Запуск Redis (мастер + 2 реплики)..."
docker compose up -d --build
echo "  Ожидание запуска сервисов..."
sleep 5
echo "  OK: Сервисы запущены"
echo ""

# ── Шаг 3: Ожидание готовности реплик ─────────────────────

echo "[3/5] Ожидание готовности реплик..."

wait_for_replicas() {
    local max_attempts=30
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        replica_info=$(docker exec redis-master redis-cli info replication 2>/dev/null)
        online_replicas=$(echo "$replica_info" | grep -c "state=online" || true)
        
        if [ "$online_replicas" -ge 2 ]; then
            echo "  OK: Реплики готовы (${online_replicas} online)"
            return 0
        fi
        
        attempt=$((attempt + 1))
        echo -n "."
        sleep 1
    done
    
    echo "  ОШИБКА: Таймаут, только ${online_replicas} реплик online"
    return 1
}

if ! wait_for_replicas; then
    echo "Реплики не готовы. Попробуйте вручную:"
    echo "  docker compose exec app python3 seed_data.py"
    exit 1
fi
echo ""

# ── Шаг 4: Заполнение данных ──────────────────────────────

echo "[4/5] Заполнение тестовых данных..."
docker compose exec -T app python3 seed_data.py
echo "  OK: Тестовые данные загружены"
echo ""

# ── Шаг 5: Тесты ──────────────────────────────────────────

echo "[5/5] Запуск тестов (dz1_check.py)..."
echo ""
echo "────────────────────────────────────────────────────────"

python3 dz1_check.py
test_exit_code=$?

echo "────────────────────────────────────────────────────────"


if [ "$KEEP_RUNNING" = false ]; then
    echo "Остановка контейнеров... (--keep чтобы оставить)"
    docker compose down -v
    echo "OK: Контейнеры остановлены"
else
    echo ""

    echo "Сервисы:"
    echo "  Flask API:       http://localhost:5001"
    echo "  Redis Master:    localhost:6379"
    echo "  Redis Replica 1: localhost:6380"
    echo "  Redis Replica 2: localhost:6381"
    echo "  Sentinel 1:      localhost:26379"
    echo "  Sentinel 2:      localhost:26380"
    echo "  Sentinel 3:      localhost:26381"
    echo ""
    echo "Контейнеры работают. Остановка: docker compose down -v"
fi
echo ""

exit $test_exit_code