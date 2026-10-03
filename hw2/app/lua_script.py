import redis

# Lua-скрипт для атомарного инкремента счетчика с TTL
LOGIN_COUNTER_SCRIPT = """
local key = KEYS[1]
local ttl = tonumber(ARGV[1])

-- Инкрементируем счетчик
local count = redis.call('INCR', key)

-- Устанавливаем TTL при первом входе или обновляем при каждом входе
redis.call('EXPIRE', key, ttl)

return count
"""

class LuaScripts:
    def __init__(self, redis_client):
        self.redis = redis_client
        # Регистрируем скрипты
        self.login_counter = self.redis.register_script(LOGIN_COUNTER_SCRIPT)
    
    def increment_login_counter(self, player_id, ttl_seconds=86400):
        """
        Атомарно инкрементирует счетчик входов и устанавливает TTL
        
        Args:
            player_id: ID игрока
            ttl_seconds: TTL в секундах (по умолчанию 24 часа)
        
        Returns:
            Текущее значение счетчика
        """
        key = f"logins:{player_id}"
        return self.login_counter(keys=[key], args=[ttl_seconds])