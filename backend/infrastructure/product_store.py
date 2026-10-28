import json
import time
import os
from backend.infrastructure.store import Store
from backend.domain.errors import Conflict, JourneyNotFound


class ProductStore(Store):
    def __init__(self, path=None):
        super().__init__(path)
        self.redis = None
        if path is None and os.getenv('REDIS_URL'):
            from redis import Redis
            self.redis = Redis.from_url(os.environ['REDIS_URL'], socket_connect_timeout=1, socket_timeout=1, decode_responses=True)
        with self.connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS journeys (id TEXT PRIMARY KEY, owner TEXT NOT NULL, version INTEGER NOT NULL, updated REAL NOT NULL, payload TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS profiles (owner TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS source_cache (key TEXT PRIMARY KEY, expires REAL NOT NULL, payload TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, owner TEXT NOT NULL, journey_id TEXT NOT NULL, quote_id TEXT NOT NULL, status TEXT NOT NULL, hotel_id TEXT NOT NULL, check_in TEXT NOT NULL, check_out TEXT NOT NULL, rooms INTEGER NOT NULL, payload TEXT NOT NULL, UNIQUE(owner,journey_id,quote_id))")

    def put_journey(self, owner, journey, expected=None):
        with self.connect() as c:
            if expected is None:
                c.execute("INSERT INTO journeys VALUES(?,?,?,?,?)",(journey['id'],owner,journey['version'],time.time(),json.dumps(journey,ensure_ascii=False)))
            else:
                n=c.execute("UPDATE journeys SET version=?,updated=?,payload=? WHERE id=? AND owner=? AND version=?",(journey['version'],time.time(),json.dumps(journey,ensure_ascii=False),journey['id'],owner,expected)).rowcount
                if n != 1: raise Conflict("Поездка изменилась в другой вкладке. Обнови её перед сохранением.")

    def get_journey(self, owner, journey_id):
        with self.connect() as c: row=c.execute("SELECT payload FROM journeys WHERE owner=? AND id=?",(owner,journey_id)).fetchone()
        if not row: raise JourneyNotFound(journey_id)
        return json.loads(row[0])

    def list_journeys(self, owner):
        with self.connect() as c: rows=c.execute("SELECT payload FROM journeys WHERE owner=? ORDER BY updated DESC LIMIT 100",(owner,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def remove_journey(self, owner, journey_id, expected):
        with self.connect() as c:
            deleted = c.execute("DELETE FROM journeys WHERE owner=? AND id=? AND version=?", (owner, journey_id, expected)).rowcount
            if deleted != 1:
                raise Conflict("Поездка изменилась перед удалением. Обнови страницу.")

    def profile(self, owner, value=None):
        with self.connect() as c:
            if value is not None: c.execute("INSERT INTO profiles VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET payload=excluded.payload",(owner,json.dumps(value,ensure_ascii=False)))
            row=c.execute("SELECT payload FROM profiles WHERE owner=?",(owner,)).fetchone()
        return json.loads(row[0]) if row else {}

    def cache_get(self, key):
        if self.redis:
            from redis.exceptions import RedisError
            try:
                value = self.redis.get('uno:source:' + key)
                return json.loads(value) if value is not None else None
            except (RedisError, ValueError):
                return None
        with self.connect() as c: row=c.execute("SELECT payload FROM source_cache WHERE key=? AND expires>?",(key,time.time())).fetchone()
        return json.loads(row[0]) if row else None

    def cache_put(self, key, payload, ttl=86400):
        if self.redis:
            from redis.exceptions import RedisError
            try:
                self.redis.setex('uno:source:' + key, max(1, int(ttl)), json.dumps(payload,ensure_ascii=False))
            except RedisError:
                pass
            return
        with self.connect() as c:c.execute("INSERT INTO source_cache VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET expires=excluded.expires,payload=excluded.payload",(key,time.time()+ttl,json.dumps(payload,ensure_ascii=False)))

    def existing_order(self,owner,journey_id,quote_id):
        with self.connect() as c:row=c.execute('SELECT payload FROM orders WHERE owner=? AND journey_id=? AND quote_id=?',(owner,journey_id,quote_id)).fetchone()
        return json.loads(row[0]) if row else None

    def journey_for_order(self,owner,order_id):
        with self.connect() as c:
            row=c.execute('SELECT journey_id FROM orders WHERE owner=? AND id=?',(owner,order_id)).fetchone()
        if not row: raise JourneyNotFound(order_id)
        return self.get_journey(owner,row[0])

    def confirm_order(self,owner,journey,order,expected):
        from datetime import date,timedelta
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            existing=c.execute('SELECT payload FROM orders WHERE owner=? AND journey_id=? AND quote_id=?',(owner,journey['id'],order['quote_id'])).fetchone()
            if existing:return json.loads(existing[0])
            from uuid import uuid4
            for _ in range(16):
                if not c.execute('SELECT 1 FROM orders WHERE id=?',(order['id'],)).fetchone(): break
                order['id']='DEMO-'+uuid4().hex[:6].upper()
            else: raise Conflict('Не удалось создать номер заказа. Повтори попытку.')
            overlaps=c.execute("SELECT check_in,check_out,rooms FROM orders WHERE hotel_id=? AND status='confirmed' AND check_in<? AND check_out>?",(order['hotel_id'],order['check_out'],order['check_in'])).fetchall()
            day=date.fromisoformat(order['check_in']);end=date.fromisoformat(order['check_out'])
            while day<end:
                occupied=sum(r[2] for r in overlaps if r[0]<=day.isoformat()<r[1])
                if occupied+order['rooms']>12:raise Conflict('На эти даты закончились модельные номера. Выбери другой отель или даты.')
                day+=timedelta(days=1)
            n=c.execute('UPDATE journeys SET version=?,updated=?,payload=? WHERE owner=? AND id=? AND version=?',(journey['version'],time.time(),json.dumps(journey,ensure_ascii=False),owner,journey['id'],expected)).rowcount
            if n!=1:raise Conflict('Поездка изменилась перед оформлением. Обнови страницу.')
            c.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?)',(order['id'],owner,journey['id'],order['quote_id'],'confirmed',order['hotel_id'],order['check_in'],order['check_out'],order['rooms'],json.dumps(order,ensure_ascii=False)))
        return order

    def cancel_order(self,owner,journey,expected):
        order=journey['order']
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            n=c.execute('UPDATE journeys SET version=?,updated=?,payload=? WHERE owner=? AND id=? AND version=?',(journey['version'],time.time(),json.dumps(journey,ensure_ascii=False),owner,journey['id'],expected)).rowcount
            if n!=1:raise Conflict('Поездка уже изменилась. Обнови страницу.')
            c.execute("UPDATE orders SET status='cancelled',payload=? WHERE owner=? AND id=?",(json.dumps(order,ensure_ascii=False),owner,order['id']))
