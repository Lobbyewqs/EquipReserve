"""Small connection adapter for the project's SQLite and MySQL stores."""
import json
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG = ROOT / 'data' / 'mysql.json'


class MySQLConnection:
    def __init__(self, config):
        import pymysql
        self.raw = pymysql.connect(**config, charset='utf8mb4', autocommit=True,
                                   cursorclass=pymysql.cursors.DictCursor,
                                   connect_timeout=10, read_timeout=60, write_timeout=60)
        self.execute('SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED')

    def execute(self, sql, args=()):
        if sql == 'BEGIN IMMEDIATE':
            self.raw.begin()
            return
        cursor = self.raw.cursor()
        sql = sql.replace('INSERT OR IGNORE', 'INSERT IGNORE').replace('?', '%s')
        cursor.execute(sql, args)
        return cursor

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def configured_store(sqlite_path=None):
    from core import Store
    if sqlite_path is not None:
        return Store(sqlite_path)
    if CONFIG.is_file():
        return Store(json.loads(CONFIG.read_text(encoding='utf-8')))
    return Store(ROOT / 'data' / 'equipreserve.sqlite3')
