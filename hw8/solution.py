# -*- coding: utf-8 -*-
# Заготовка решения ДЗ_3 (Cassandra). Заполняйте тела функций с TODO -
# остальное (стенд, контрольные данные, проверки) уже готово в lab.py.
# Служебный lab.py менять не нужно; контракты и порядок опытов - в Задание.md.

import json
from datetime import datetime, timedelta

from cassandra.query import ConsistencyLevel

# База отсчёта времени событий: 2026-01-01T00:00:00Z. Важно: без таймзоны
# (наивный UTC) - драйвер возвращает timestamp без tzinfo, и сценарий data
# сравнивает прочитанные значения именно с наивной базой.
BASE_EVENT_TIME = datetime(2026, 1, 1)

# Типы событий: циклично по индексу i - login, purchase, view.
EVENT_TYPES = ['login', 'purchase', 'view']


def create_tables(session):
    session.execute('''
    CREATE TABLE IF NOT EXISTS hw3.user_actions (
        user_id int,
        event_time timestamp,
        event_type text,
        payload text,
        PRIMARY KEY (user_id, event_time)
    ) WITH CLUSTERING ORDER BY (event_time DESC)
       AND COMPRESSION = {'class': 'LZ4Compressor'}
    ''')
    session.execute('''
    CREATE TABLE IF NOT EXISTS hw3.user_actions_none (
        user_id int,
        event_time timestamp,
        event_type text,
        payload text,
        PRIMARY KEY (user_id, event_time)
    ) WITH CLUSTERING ORDER BY (event_time DESC)
        AND COMPRESSION = {'enabled': 'false'}
    ''')
    return ['user_actions', 'user_actions_none']




    # Разделы 3-4, сценарии bulk и consistency. Вставьте n событий
    # пользователя user_id в таблицу table (сценарий передаёт и
    # 'user_actions', и 'user_actions_none' - обе должны получить данные).
    #
    # Событие с номером i (i = 0..n-1):
    #   event_time = BASE_EVENT_TIME + timedelta(minutes=i)
    #   event_type - по циклу из EVENT_TYPES (события чередуются:
    #   login, purchase, view)
    #   payload - словарь с полем seq, равным i, сериализованный в JSON
    #
    # Вставка - через PreparedStatement: session.prepare(...) один раз,
    # затем bind и execute для каждого события. Требование задания.
    # Уровень консистентности задавайте на отдельном утверждении
    # (bound.consistency_level = consistency), а не на сессии: сессия
    # у сценария consistency одна на все четыре замера.
    #
    # Верните n - число вставленных событий.
def insert_events(session, table, user_id, n, consistency):
    prepared = session.prepare(f"INSERT INTO hw3.{table} (user_id, event_time, event_type, payload) VALUES (?, ?, ?, ?)")
    for i in range(n):
        event_time = BASE_EVENT_TIME + timedelta(minutes=i)
        event_type = EVENT_TYPES[i % 3]
        payload = json.dumps({"seq": i})
        bound = prepared.bind([user_id, event_time, event_type, payload])
        bound.consistency_level = consistency
        session.execute(bound)
    return n

   

    # Разделы 3-4, сценарии bulk и consistency. Прочитайте limit последних
    # событий пользователя user_id из таблицы table.
    #
    # Запрос: SELECT ... WHERE user_id = ? ORDER BY event_time DESC LIMIT ?.
    # Порядок по убыванию уже даёт кластеризация таблицы - сортировать
    # на клиенте не нужно. Уровень консистентности - на утверждении,
    # как в insert_events.
    #
    # Верните список строк результата - list(session.execute(...)):
    # сценарий берёт из строк поля event_time и event_type.
def read_last(session, table, user_id, limit, consistency):
    prepared = session.prepare(f"SELECT user_id, event_time, event_type, payload from hw3.{table} WHERE  user_id = ? LIMIT ?")
    bound = prepared.bind([user_id, limit])
    bound.consistency_level = consistency
    return list(session.execute(bound))
