"""Gracefully stop only the MySQL instance configured for this project."""
import json

import pymysql

from mysql_local import ADMIN_CONFIG, DATA


config = json.loads(ADMIN_CONFIG.read_text(encoding='utf-8'))
connection = pymysql.connect(**config, autocommit=True)
try:
    with connection.cursor() as cursor:
        cursor.execute('SELECT @@datadir')
        from pathlib import Path
        actual = Path(cursor.fetchone()[0]).resolve()
        expected = (DATA / 'mysql-server').resolve()
        if actual != expected:
            raise RuntimeError('连接的实例不是本项目的数据目录，拒绝关闭。')
        cursor.execute('SHUTDOWN')
finally:
    connection.close()
print('本项目的 MySQL 已安全关闭。')
