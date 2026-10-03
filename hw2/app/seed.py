"""
Скрипт для предзаполнения тестовых данных в Redis
Необходим для прохождения автоматической проверки dz1_check.py
"""

import json
import time
from redis_client import init_redis, get_master

def seed_test_data():
    """Заполняет Redis тестовыми данными для проверки"""
    
    print("🌱 Начало заполнения тестовых данных...\n")
    
    master = get_master()
    
    # 1. Создаем игрока 1001 (профиль)
    print("1️⃣  Создаем профиль игрока 1001...")
    master.hset("player:1001", mapping={
        "name": "TestPlayer",
        "level": "15",
        "region": "eu",
        "created_at": str(int(time.time()))
    })
    print("   ✓ player:1001 создан (Hash)")
    
    # 2. Добавляем игрока в лидерборд
    print("2️⃣  Добавляем игрока в лидерборд...")
    master.zadd("tournament:main", {"1001": 1500})
    master.zadd("tournament:main", {"1002": 1200})
    master.zadd("tournament:main", {"1003": 1800})
    print("   ✓ tournament:main содержит игроков (Sorted Set)")
    
    # 3. Добавляем достижения игроку 1001
    print("3️⃣  Добавляем достижения игроку 1001...")
    master.sadd("achievements:1001", "first_win", "speed_run", "explorer")
    print("   ✓ achievements:1001 содержит достижения (Set)")
    
    # 4. Создаем счетчик входов с TTL
    print("4️⃣  Создаем счетчик входов...")
    master.set("logins:1001", 5, ex=86400)
    print("   ✓ logins:1001 = 5, TTL = 86400 сек (String)")
    
    # 5. Заполняем кэш профиля
    print("5️⃣  Заполняем кэш профиля...")
    player_data = master.hgetall("player:1001")
    master.set("cache:player:1001", json.dumps(player_data), ex=60)
    print("   ✓ cache:player:1001 создан, TTL = 60 сек")
    
    # 6. Создаем stream с уведомлениями
    print("6️⃣  Создаем stream уведомлений...")
    master.xadd('notifications', {
        'player_id': '1001',
        'type': 'level_up',
        'message': 'Player leveled up',
        'timestamp': str(int(time.time()))
    })
    master.xadd('notifications', {
        'player_id': '1002',
        'type': 'achievement',
        'message': 'New achievement unlocked',
        'timestamp': str(int(time.time()))
    })
    print("   ✓ notifications stream создан (Stream)")
    
    # 7. Создаем consumer group
    print("7️⃣  Создаем consumer group...")
    try:
        master.xgroup_create('notifications', 'notifications-group', id='0', mkstream=True)
        print("   ✓ notifications-group создана")
    except Exception as e:
        if "BUSYGROUP" in str(e):
            print("   ✓ notifications-group уже существует")
        else:
            raise e
    
    # 8. Массовое создание профилей через pipeline
    print("8️⃣  Массовое создание профилей через pipeline...")
    pipeline = master.pipeline()
    
    for i in range(1004, 1020):  # Создаем 16 дополнительных игроков
        pipeline.hset(f"player:{i}", mapping={
            "name": f"Player{i}",
            "level": str(i % 20 + 1),
            "region": "eu",
            "created_at": str(int(time.time()))
        })
    
    pipeline.execute()
    print("   ✓ Создано 16 дополнительных профилей через pipeline")
    
    # 9. Проверяем итоговое состояние
    print("\n📊 Итоговое состояние Redis:")
    print(f"   • player:1001 тип: {master.type('player:1001')}")
    print(f"   • tournament:main размер: {master.zcard('tournament:main')}")
    print(f"   • achievements:1001 размер: {master.scard('achievements:1001')}")
    print(f"   • logins:1001 значение: {master.get('logins:1001')}, TTL: {master.ttl('logins:1001')}")
    print(f"   • cache:player:1001 TTL: {master.ttl('cache:player:1001')}")
    print(f"   • notifications длина: {master.xlen('notifications')}")
    
    # Считаем все профили
    cursor = '0'
    count = 0
    while True:
        cursor, keys = master.scan(cursor=cursor, match='player:*', count=100)
        count += len(keys)
        if cursor == '0':
            break
    
    print(f"   • Всего профилей player:*: {count}")
    
    print("\n✅ Тестовые данные успешно заполнены!")
    print("🎯 Теперь можно запускать dz1_check.py для проверки\n")

if __name__ == '__main__':
    # Инициализируем Redis
    if not init_redis():
        print("❌ Не удалось подключиться к Redis. Завершение.")
        exit(1)
    
    # Заполняем данные
    seed_test_data()