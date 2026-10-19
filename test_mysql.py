"""Real MySQL tests. Each test owns a fresh, randomly named disposable database."""
import json
import re
import secrets
import concurrent.futures
import unittest
from pathlib import Path

import pymysql

import test_platform
from core import Store
from migrate_mysql import migrate
from mysql_local import ADMIN_CONFIG


@unittest.skipUnless(ADMIN_CONFIG.exists(), '需要本机已配置的 MySQL 测试管理员连接')
class MySQLPlatformTests(test_platform.PlatformTests):
    def make_store(self, path, clock):
        config = json.loads(ADMIN_CONFIG.read_text(encoding='utf-8'))
        name = 'equipreserve_test_' + secrets.token_hex(8)
        assert re.fullmatch(r'equipreserve_test_[0-9a-f]{16}', name)
        admin = pymysql.connect(**config, autocommit=True)
        with admin.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin')

        def cleanup():
            try:
                with admin.cursor() as cursor:
                    cursor.execute(f'DROP DATABASE `{name}`')
            finally:
                admin.close()
        self.addCleanup(cleanup)
        return Store({**config, 'database': name}, clock)

    def test_sqlite_migration_preserves_password_history_and_current_loan(self):
        source = Store(Path(self.tmp.name) / 'migration.sqlite3', lambda: self.now)
        source.initialize()
        db = source.connect()
        db.execute("INSERT INTO app_user VALUES(1,'student',?,'USER',1)", (self.hashed,))
        db.execute("INSERT INTO app_user VALUES(2,'admin',?,'ADMIN',1)", (self.hashed,))
        db.execute("INSERT INTO device(id,asset_code,name,category) VALUES(1,'M1','相机','影像')")
        db.close()
        actor = {'id': 1, 'role': 'USER'}
        admin = {'id': 2, 'role': 'ADMIN'}
        target = source.mutate(actor, 'reserve', 'migration-reserve', {'deviceId': 1, 'slotStart': self.start})[0]['id']
        self.now = self.now.replace(hour=9)
        source.mutate(admin, 'checkout', 'migration-checkout', {}, target)
        fresh = self.make_store(None, lambda: self.now)
        result = migrate(source.path, fresh.path)
        self.assertEqual(result['counts']['reservation'], 1)
        self.assertEqual(fresh.query('SELECT current_loan_id FROM device')[0]['current_loan_id'], target)
        self.assertEqual(fresh.query('SELECT status FROM reservation')[0]['status'], 'BORROWED')
        token, _ = fresh.login('student', self.password)
        self.assertEqual(fresh.authenticate(token)['id'], 1)
        with self.assertRaises(ValueError):
            migrate(source.path, fresh.path)

    def test_database_enforces_one_physical_loan(self):
        db = self.store.connect()
        try:
            for key in range(2):
                if key == 0:
                    db.execute("INSERT INTO reservation(user_id,device_id,slot_start,slot_end,pickup_deadline,status,created_at) VALUES(1,1,'a','b','b','BORROWED','a')")
                else:
                    with self.assertRaises(pymysql.err.IntegrityError):
                        db.execute("INSERT INTO reservation(user_id,device_id,slot_start,slot_end,pickup_deadline,status,created_at) VALUES(2,1,'c','d','d','BORROWED','c')")
        finally:
            db.close()

    def test_other_device_does_not_wait_for_locked_device(self):
        db = self.store.connect()
        db.execute("INSERT INTO device(id,asset_code,name,category) VALUES(2,'D2','Second','Camera')")
        db.execute('BEGIN IMMEDIATE')
        self.store.lock_device(db, 1)
        pool = concurrent.futures.ThreadPoolExecutor(1)
        try:
            future = pool.submit(self.store.mutate, self.user, 'reserve', 'independent-device',
                                 {'deviceId': 2, 'slotStart': self.start})
            result, status = future.result(timeout=5)
            self.assertEqual(status, 201)
            self.assertEqual(self.store.query('SELECT device_id FROM reservation WHERE id=?', (result['id'],))[0]['device_id'], 2)
        finally:
            db.rollback()
            db.close()
            pool.shutdown()

    def test_idempotency_keys_keep_case_and_trailing_spaces_distinct(self):
        morning = self.reserve(key='Key')
        afternoon = self.reserve(key='Key ', start=next(s for s, _, _ in self.store.slot_times() if s > self.start))
        self.assertNotEqual(morning, afternoon)
        self.assertEqual(self.store.query('SELECT count(*) n FROM idempotency_record')[0]['n'], 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
