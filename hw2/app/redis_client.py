from redis.sentinel import Sentinel
import redis
import os

# Настройки Sentinel
SENTINEL_HOSTS = [
    ('sentinel-1', 26379),
    ('sentinel-2', 26380),
    ('sentinel-3', 26381),
]
MASTER_NAME = 'mymaster'

# Глобальные подключения
sentinel = None
master_client = None
slave_client = None

def init_redis():
    """Инициализация подключения к Redis через Sentinel"""
    global sentinel, master_client, slave_client
    
    try:
        # Создаем Sentinel подключение
        sentinel = Sentinel(SENTINEL_HOSTS, socket_timeout=5)
        
        # Получаем мастер для записи
        master_client = sentinel.master_for(
            MASTER_NAME,
            socket_timeout=5,
            retry_on_timeout=True,
            decode_responses=True
        )
        
        # Получаем реплику для чтения
        slave_client = sentinel.slave_for(
            MASTER_NAME,
            socket_timeout=5,
            retry_on_timeout=True,
            decode_responses=True
        )
        
        # Проверяем соединение
        master_client.ping()
        print("✓ Подключение к Redis через Sentinel установлено")
        return True
        
    except Exception as e:
        print(f"✗ Ошибка подключения к Redis: {e}")
        return False

def get_master():
    """Получить мастер-клиент для записи"""
    return master_client

def get_slave():
    """Получить slave-клиент для чтения"""
    return slave_client