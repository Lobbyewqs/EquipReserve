import concurrent.futures
import json
import secrets
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from core import BusinessError, SHANGHAI, Store, password_hash, stamp
from server import make_server


class PlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = secrets.token_urlsafe(12)
        cls.hashed = password_hash(cls.password)

    def setUp(self):
        test_root = Path(__file__).parent / 'data' / 'tests'
        test_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=test_root)
        self.now = datetime(2026, 10, 17, 8, tzinfo=SHANGHAI)
        self.store = Store(Path(self.tmp.name) / 'test.db', lambda: self.now)
        self.store.initialize()
        db = self.store.connect()
        for n in range(1, 102):
            db.execute('INSERT INTO app_user(id,username,password_hash,role) VALUES(?,?,?,?)', (n, f'user{n}', self.hashed, 'ADMIN' if n == 101 else 'USER'))
        db.execute("INSERT INTO device(id,asset_code,name,category) VALUES(1,'D1','Camera','Camera')")
        db.close()
        self.user = {'id': 1, 'role': 'USER'}
        self.admin = {'id': 101, 'role': 'ADMIN'}
        self.start = stamp(self.now.replace(hour=9))

    def tearDown(self):
        self.tmp.cleanup()

    def reserve(self, user=None, key=None, start=None):
        return self.store.mutate(user or self.user, 'reserve', key or secrets.token_hex(8), {'deviceId': 1, 'slotStart': start or self.start})[0]['id']

    def op(self, action, target, actor=None, key=None):
        return self.store.mutate(actor or self.admin, action, key or secrets.token_hex(8), {}, target)[0]

    def row(self, target):
        return self.store.query('SELECT * FROM reservation WHERE id=?', (target,))[0]

    def test_100_users_compete_for_one_slot(self):
        def attempt(n):
            try:
                return self.reserve({'id': n, 'role': 'USER'})
            except BusinessError as e:
                return e.code
        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as pool:
            results = list(pool.map(attempt, range(1, 101)))
        self.assertEqual(sum(type(r) is int for r in results), 1)
        self.assertEqual(results.count('SLOT_OCCUPIED'), 99)
        self.assertEqual(len(self.store.query('SELECT * FROM slot_occupancy')), 1)
        self.assertEqual(len(self.store.query('SELECT * FROM reservation')), 1)
        print(f'\n100 contenders: {time.perf_counter()-started:.3f}s (correctness run, not throughput benchmark)')

    def test_20_simultaneous_replays_and_conflict(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            ids = list(pool.map(lambda _: self.reserve(key='same'), range(20)))
        self.assertEqual(len(set(ids)), 1)
        with self.assertRaises(BusinessError) as e:
            self.reserve(key='same', start=stamp(self.now.replace(hour=14)))
        self.assertEqual(e.exception.code, 'KEY_CONFLICT')

    def test_rollback_after_occupancy(self):
        def fail(_):
            raise RuntimeError('injected fault')
        self.store.fault = fail
        with self.assertRaises(RuntimeError):
            self.reserve(key='retry')
        for table in ('reservation', 'slot_occupancy', 'idempotency_record', 'audit_event'):
            self.assertEqual(self.store.query(f'SELECT count(*) n FROM {table}')[0]['n'], 0)
        self.store.fault = None
        self.reserve(key='retry')

    def test_cancel_retry_cannot_delete_new_occupancy(self):
        first = self.reserve()
        self.op('cancel', first)
        second = self.reserve()
        self.op('cancel', first)
        self.assertEqual(self.store.query('SELECT reservation_id FROM slot_occupancy')[0]['reservation_id'], second)

    def test_cancel_checkout_race_at_start(self):
        target = self.reserve()
        self.now = self.now.replace(hour=9)
        def run(action):
            try:
                return self.op(action, target)['status']
            except BusinessError as e:
                return e.code
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            result = list(pool.map(run, ['cancel', 'checkout']))
        self.assertEqual(result, ['CANNOT_CANCEL', 'BORROWED'])
        self.assertEqual(self.store.query('SELECT current_loan_id FROM device')[0]['current_loan_id'], target)

    def test_checkout_expire_race_at_deadline(self):
        target = self.reserve()
        self.now = self.now.replace(hour=9, minute=15)
        def checkout():
            try:
                return self.op('checkout', target)
            except BusinessError:
                return None
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            a, b = pool.submit(checkout), pool.submit(self.store.expire)
            self.assertIsNone(a.result())
            b.result()
        self.assertEqual(self.row(target)['status'], 'EXPIRED')
        self.assertIsNone(self.store.query('SELECT current_loan_id FROM device')[0]['current_loan_id'])

    def test_restart_sweep_idempotent(self):
        target = self.reserve()
        self.now += timedelta(hours=2)
        restarted = Store(self.store.path, lambda: self.now)
        restarted.initialize()
        self.assertEqual(restarted.expire(), 1)
        self.assertEqual(restarted.expire(), 0)
        self.assertEqual(self.row(target)['status'], 'EXPIRED')

    def test_overdue_blocks_later_pickup_and_old_return_retry_safe(self):
        first = self.reserve()
        second = self.reserve(start=stamp(self.now.replace(hour=14)))
        self.now = self.now.replace(hour=9)
        self.op('checkout', first)
        self.now = self.now.replace(hour=14)
        self.assertTrue(next(r for r in self.store.reservations(self.user) if r['id'] == first)['overdue'])
        with self.assertRaises(BusinessError) as e:
            self.op('checkout', second)
        self.assertEqual(e.exception.code, 'PREVIOUS_LOAN')
        self.op('return', first)
        self.op('checkout', second)
        self.op('return', first)
        self.assertEqual(self.store.query('SELECT current_loan_id FROM device')[0]['current_loan_id'], second)

    def test_disabled_device_blocks_reserve_pickup_allows_return(self):
        target = self.reserve()
        self.store.mutate(self.admin, 'device', 'off', {'enabled': False}, 1)
        self.now = self.now.replace(hour=9)
        with self.assertRaises(BusinessError):
            self.op('checkout', target)
        with self.assertRaises(BusinessError):
            self.reserve(start=stamp(self.now.replace(hour=14)))
        self.store.mutate(self.admin, 'device', 'on', {'enabled': True}, 1)
        self.op('checkout', target)
        self.store.mutate(self.admin, 'device', 'off-again', {'enabled': False}, 1)
        self.op('return', target)
        self.assertEqual(self.row(target)['status'], 'RETURNED')
        self.assertEqual(len(self.store.query('SELECT * FROM slot_occupancy')), 1)

    def test_ownership_and_role(self):
        target = self.reserve()
        for action, actor, status in [('cancel', {'id': 2, 'role': 'USER'}, 404), ('checkout', self.user, 403), ('return', self.user, 403)]:
            with self.assertRaises(BusinessError) as e:
                self.op(action, target, actor)
            self.assertEqual(e.exception.status, status)

    def test_local_password_reset_preserves_records_and_revokes_session(self):
        from reset_password import reset_password
        target = self.reserve()
        token, _ = self.store.login('user1', self.password)
        replacement = secrets.token_urlsafe(16)
        reset_password(self.store, 'user1', replacement)
        with self.assertRaises(BusinessError):
            self.store.login('user1', self.password)
        with self.assertRaises(BusinessError):
            self.store.authenticate(token)
        self.assertEqual(self.store.login('user1', replacement)[1]['id'], 1)
        self.assertEqual(self.row(target)['status'], 'CONFIRMED')
        self.assertEqual(len(self.store.query('SELECT * FROM slot_occupancy')), 1)
        self.assertEqual(self.store.login('user2', self.password)[1]['id'], 2)

    def test_time_window_boundaries(self):
        self.assertEqual(len(self.store.slots(1)['slots']), 28)
        target = self.reserve()
        with self.assertRaises(BusinessError):
            self.op('checkout', target)
        self.now = self.now.replace(hour=9, minute=14, second=59)
        self.op('checkout', target)
        self.op('return', target)
        with self.assertRaises(BusinessError):
            self.reserve(start=stamp((self.now + timedelta(days=14)).replace(hour=14, minute=0, second=0)))

    def test_real_http_auth_csrf_and_roundtrip(self):
        server = make_server(self.store, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        def request(path, method='GET', body=None, headers=None):
            req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type':'application/json', **(headers or {})})
            try:
                return urllib.request.urlopen(req)
            except urllib.error.HTTPError as error:
                return error
        try:
            with request('/') as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b'EquipReserve', response.read())
            with request('/api/devices') as response:
                self.assertEqual(response.status, 401)
            with request('/api/session', 'POST', {'username':'user1','password':self.password}) as response:
                cookie = response.headers['Set-Cookie'].split(';')[0]
                csrf = json.load(response)['user']['csrf']
            headers = {'Cookie':cookie,'Idempotency-Key':'http-reserve'}
            payload = {'deviceId':1,'slotStart':self.start}
            with request('/api/reservations','POST',payload,headers) as response:
                self.assertEqual(response.status, 403)
            headers['X-CSRF-Token'] = csrf
            with request('/api/reservations','POST',payload,headers) as response:
                self.assertEqual(response.status, 201)
                target = json.load(response)['id']
            with request('/api/reservations','POST',payload,headers) as response:
                self.assertEqual(json.load(response)['id'], target)
            with request('/api/admin/audit',headers=headers) as response:
                self.assertEqual(response.status, 403)
            with request('/api/session','DELETE',headers=headers) as response:
                self.assertEqual(response.status, 200)
            with request('/api/devices',headers=headers) as response:
                self.assertEqual(response.status, 401)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main(verbosity=2)
