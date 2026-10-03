from flask import Flask, request, jsonify
import json
import time
import threading
from redis_client import init_redis, get_master, get_slave
from lua_scripts import LuaScripts

app = Flask(__name__)

# Глобальные объекты
lua_scripts = None
consumer_thread = None
consumer_running = False

def init_streams():
    """Инициализация Streams и consumer groups"""
    try:
        master = get_master()
        # Создаем consumer group, если она не существует
        try:
            master.xgroup_create('notifications', 'notifications-group', id='0', mkstream=True)
            print("✓ Consumer group 'notifications-group' создана")
        except Exception as e:
            if "BUSYGROUP" in str(e):
                print("✓ Consumer group 'notifications-group' уже существует")
            else:
                raise e
    except Exception as e:
        print(f"✗ Ошибка инициализации streams: {e}")

def notification_consumer():
    """Фоновый consumer для обработки уведомлений"""
    global consumer_running
    master = get_master()
    consumer_name = "consumer-1"
    
    print("✓ Notification consumer запущен")
    
    while consumer_running:
        try:
            # Читаем сообщения из группы
            messages = master.xreadgroup(
                groupname='notifications-group',
                consumername=consumer_name,
                streams={'notifications': '>'},
                count=10,
                block=1000  # Блокируем на 1 секунду
            )
            
            if messages:
                for stream, message_list in messages:
                    for message_id, message_data in message_list:
                        # Обрабатываем сообщение
                        print(f"📨 Получено уведомление: {message_data}")
                        
                        # Подтверждаем обработку
                        master.xack('notifications', 'notifications-group', message_id)
                        
        except Exception as e:
            print(f"✗ Ошибка в consumer: {e}")
            time.sleep(1)

# ==================== API ENDPOINTS ====================

@app.route('/api/players/<int:player_id>', methods=['POST'])
def create_or_update_player(player_id):
    """Создание/обновление профиля игрока"""
    data = request.json
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    master = get_master()
    
    # Подготавливаем данные для HSET
    fields = {}
    if 'name' in data:
        fields['name'] = data['name']
    if 'level' in data:
        fields['level'] = str(data['level'])
    if 'region' in data:
        fields['region'] = data['region']
    if 'created_at' in data:
        fields['created_at'] = str(data['created_at'])
    else:
        fields['created_at'] = str(int(time.time()))
    
    # Записываем в Redis Hash
    master.hset(f"player:{player_id}", mapping=fields)
    
    # Инвалидируем кэш
    master.delete(f"cache:player:{player_id}")
    
    return jsonify({"status": "success", "player_id": player_id}), 200

@app.route('/api/players/<int:player_id>', methods=['GET'])
def get_player(player_id):
    """Получение профиля игрока с кэшированием"""
    master = get_master()
    
    # Сначала проверяем кэш
    cached = master.get(f"cache:player:{player_id}")
    
    if cached:
        # Cache hit
        return jsonify(json.loads(cached)), 200
    
    # Cache miss - читаем из основного хранилища
    player_data = master.hgetall(f"player:{player_id}")
    
    if not player_data:
        return jsonify({"error": "Player not found"}), 404
    
    # Сериализуем в JSON и сохраняем в кэш с TTL 60 секунд
    json_data = json.dumps(player_data)
    master.set(f"cache:player:{player_id}", json_data, ex=60)
    
    return jsonify(player_data), 200

@app.route('/api/players/<int:player_id>/level', methods=['PATCH'])
def update_player_level(player_id):
    """Обновление уровня игрока"""
    data = request.json
    
    if not data or 'delta' not in data:
        return jsonify({"error": "delta is required"}), 400
    
    master = get_master()
    
    # Увеличиваем уровень
    new_level = master.hincrby(f"player:{player_id}", "level", data['delta'])
    
    # Инвалидируем кэш
    master.delete(f"cache:player:{player_id}")
    
    # Отправляем уведомление в stream
    master.xadd('notifications', {
        'player_id': str(player_id),
        'type': 'level_up',
        'message': f'Player {player_id} leveled up to {new_level}',
        'timestamp': str(int(time.time())),
        'new_level': str(new_level)
    })
    
    return jsonify({
        "status": "success",
        "player_id": player_id,
        "new_level": new_level
    }), 200

@app.route('/api/players/<int:player_id>/login', methods=['POST'])
def record_login(player_id):
    """Фиксация входа игрока (Lua-скрипт)"""
    master = get_master()
    
    # Используем Lua-скрипт для атомарной операции
    count = lua_scripts.increment_login_counter(player_id, ttl_seconds=86400)
    
    return jsonify({
        "status": "success",
        "player_id": player_id,
        "login_count": count,
        "ttl_seconds": 86400
    }), 200

@app.route('/api/leaderboard/score', methods=['POST'])
def add_score():
    """Добавление/обновление очков в лидерборде"""
    data = request.json
    
    if not data or 'player_id' not in data or 'score' not in data:
        return jsonify({"error": "player_id and score are required"}), 400
    
    master = get_master()
    
    # Увеличиваем очки игрока
    new_score = master.zincrby('tournament:main', data['score'], str(data['player_id']))
    
    return jsonify({
        "status": "success",
        "player_id": data['player_id'],
        "new_score": new_score
    }), 200

@app.route('/api/leaderboard/top', methods=['GET'])
def get_leaderboard_top():
    """Получение топ игроков"""
    limit = request.args.get('limit', 10, type=int)
    
    slave = get_slave()
    
    # Получаем топ игроков с очками
    top_players = slave.zrevrange('tournament:main', 0, limit - 1, withscores=True)
    
    # Форматируем результат
    result = [
        {"player_id": player_id, "score": score}
        for player_id, score in top_players
    ]
    
    return jsonify(result), 200

@app.route('/api/leaderboard/rank/<int:player_id>', methods=['GET'])
def get_player_rank(player_id):
    """Получение места игрока в лидерборде"""
    slave = get_slave()
    
    # Получаем ранг игрока (0-based, в порядке возрастания)
    rank = slave.zrank('tournament:main', str(player_id))
    
    if rank is None:
        return jsonify({"error": "Player not found in leaderboard"}), 404
    
    # Получаем общее количество игроков
    total = slave.zcard('tournament:main')
    
    # Конвертируем в 1-based ранг в порядке убывания
    position = total - rank
    
    return jsonify({
        "player_id": player_id,
        "rank": position,
        "total_players": total
    }), 200

@app.route('/api/players/<int:player_id>/achievements', methods=['POST'])
def add_achievement(player_id):
    """Добавление достижения игроку"""
    data = request.json
    
    if not data or 'achievement_name' not in data:
        return jsonify({"error": "achievement_name is required"}), 400
    
    master = get_master()
    
    # Добавляем достижение в множество
    added = master.sadd(f"achievements:{player_id}", data['achievement_name'])
    
    return jsonify({
        "status": "success",
        "player_id": player_id,
        "achievement": data['achievement_name'],
        "new": bool(added)
    }), 200

@app.route('/api/players/<int:player_id>/achievements/<achievement_name>', methods=['GET'])
def check_achievement(player_id, achievement_name):
    """Проверка наличия достижения у игрока"""
    slave = get_slave()
    
    # Проверяем наличие достижения
    has_achievement = slave.sismember(f"achievements:{player_id}", achievement_name)
    
    return jsonify({
        "player_id": player_id,
        "achievement": achievement_name,
        "has_achievement": bool(has_achievement)
    }), 200

@app.route('/api/players/<int:player_id1>/achievements/common/<int:player_id2>', methods=['GET'])
def get_common_achievements(player_id1, player_id2):
    """Получение общих достижений двух игроков"""
    slave = get_slave()
    
    # Находим пересечение множеств достижений
    common = slave.sinter(f"achievements:{player_id1}", f"achievements:{player_id2}")
    
    return jsonify({
        "player1_id": player_id1,
        "player2_id": player_id2,
        "common_achievements": list(common)
    }), 200

@app.route('/api/players/batch', methods=['POST'])
def batch_create_players():
    """Массовое создание профилей через pipeline"""
    data = request.json
    
    if not data or 'players' not in data:
        return jsonify({"error": "players array is required"}), 400
    
    master = get_master()
    players = data['players']
    
    # Используем pipeline для массовой загрузки
    pipeline = master.pipeline()
    
    for player in players:
        player_id = player.get('id')
        if not player_id:
            continue
        
        # Подготавливаем поля
        fields = {
            'name': player.get('name', ''),
            'level': str(player.get('level', 1)),
            'region': player.get('region', ''),
            'created_at': str(int(time.time()))
        }
        
        # Добавляем команду в pipeline
        pipeline.hset(f"player:{player_id}", mapping=fields)
    
    # Выполняем все команды одной пачкой
    start_time = time.time()
    results = pipeline.execute()
    duration = time.time() - start_time
    
    return jsonify({
        "status": "success",
        "players_created": len(players),
        "duration_seconds": round(duration, 3),
        "method": "pipeline"
    }), 200

@app.route('/api/init', methods=['POST'])
def initialize_data():
    """Инициализация тестовых данных для проверки"""
    master = get_master()
    
    try:
        # 1. Создаем игрока 1001
        master.hset("player:1001", mapping={
            "name": "TestPlayer",
            "level": "10",
            "region": "eu",
            "created_at": str(int(time.time()))
        })
        
        # 2. Добавляем в лидерборд
        master.zadd("tournament:main", {"1001": 1500})
        
        # 3. Добавляем достижения
        master.sadd("achievements:1001", "first_win", "speed_run", "explorer")
        
        # 4. Фиксируем вход (создаем счетчик с TTL)
        lua_scripts.increment_login_counter(1001, ttl_seconds=86400)
        
        # 5. Заполняем кэш (имитируем GET запрос)
        player_data = master.hgetall("player:1001")
        master.set("cache:player:1001", json.dumps(player_data), ex=60)
        
        # 6. Добавляем сообщение в stream
        master.xadd('notifications', {
            'player_id': '1001',
            'type': 'init',
            'message': 'System initialized',
            'timestamp': str(int(time.time()))
        })
        
        # 7. Создаем еще 15 игроков через pipeline
        pipeline = master.pipeline()
        for i in range(1002, 1017):
            pipeline.hset(f"player:{i}", mapping={
                "name": f"Player{i}",
                "level": str(i % 20 + 1),
                "region": "eu",
                "created_at": str(int(time.time()))
            })
            pipeline.zadd("tournament:main", {str(i): i * 100})
        
        pipeline.execute()
        
        return jsonify({
            "status": "success",
            "message": "Test data initialized",
            "players_created": 16
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Проверка здоровья приложения"""
    try:
        master = get_master()
        master.ping()
        return jsonify({"status": "healthy", "redis": "connected"}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

if __name__ == '__main__':
    # Инициализируем Redis
    if not init_redis():
        print("Не удалось подключиться к Redis. Завершение.")
        exit(1)
    
    # Инициализируем Lua-скрипты
    lua_scripts = LuaScripts(get_master())
    
    # Инициализируем streams
    init_streams()
    
    # Запускаем consumer в отдельном потоке
    consumer_running = True
    consumer_thread = threading.Thread(target=notification_consumer, daemon=True)
    consumer_thread.start()
    
    print("\n🚀 GameHub API запущен на http://localhost:5001")
    print("📊 Доступные эндпоинты:")
    print("   POST   /api/players/<id>              - Создать/обновить профиль")
    print("   GET    /api/players/<id>              - Получить профиль (с кэшем)")
    print("   PATCH  /api/players/<id>/level        - Обновить уровень")
    print("   POST   /api/players/<id>/login        - Зафиксировать вход")
    print("   POST   /api/leaderboard/score         - Добавить очки")
    print("   GET    /api/leaderboard/top            - Топ игроков")
    print("   GET    /api/leaderboard/rank/<id>      - Место игрока")
    print("   POST   /api/players/<id>/achievements  - Добавить достижение")
    print("   GET    /api/players/<id>/achievements/<name> - Проверить достижение")
    print("   GET    /api/players/<id1>/achievements/common/<id2> - Общие достижения")
    print("   POST   /api/players/batch              - Массовое создание")
    print("   POST   /api/init                       - Инициализация тестовых данных")
    print("   GET    /health                         - Проверка здоровья\n")
    
    # Запускаем Flask
    app.run(host='0.0.0.0', port=5000, debug=False)