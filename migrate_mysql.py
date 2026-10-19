"""Copy a consistent SQLite snapshot into an empty MySQL database, then activate it."""
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from core import Store
from mysql_local import DATA, save_private_json

TABLES = ('app_user', 'device', 'reservation', 'slot_occupancy', 'idempotency_record', 'audit_event', 'session')


def migrate(source_path, config):
    destination = Store(config)
    destination.initialize()
    if any(destination.query(f'SELECT count(*) n FROM {table}')[0]['n'] for table in TABLES):
        raise ValueError('目标 MySQL 库不是空库，拒绝覆盖。')
    backup_dir = DATA / 'backups'
    backup_dir.mkdir(exist_ok=True)
    snapshot = backup_dir / ('sqlite-before-mysql-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
    source = sqlite3.connect(source_path)
    backup = sqlite3.connect(snapshot)
    try:
        source.backup(backup)
    finally:
        backup.close()
        source.close()
    source = sqlite3.connect(snapshot)
    source.row_factory = sqlite3.Row
    db = destination.connect()
    counts = {}
    try:
        db.execute('BEGIN IMMEDIATE')
        loan_links = []
        for table in TABLES:
            rows = list(source.execute(f'SELECT * FROM {table}'))
            counts[table] = len(rows)
            for row in rows:
                data = dict(row)
                if table == 'device':
                    if data['current_loan_id'] is not None:
                        loan_links.append((data['current_loan_id'], data['id']))
                    data['current_loan_id'] = None
                columns = ','.join(data)
                marks = ','.join('?' for _ in data)
                db.execute(f'INSERT INTO {table} ({columns}) VALUES({marks})', tuple(data.values()))
        for loan_id, device_id in loan_links:
            db.execute('UPDATE device SET current_loan_id=? WHERE id=?', (loan_id, device_id))
        # Compare every copied column before committing, including password hashes and history.
        for table in TABLES:
            columns = [row['name'] for row in source.execute(f'PRAGMA table_info({table})')]
            order = ','.join(columns)
            original = [tuple(row) for row in source.execute(f'SELECT {order} FROM {table} ORDER BY {order}')]
            copied = [tuple(row[column] for column in columns) for row in db.execute(f'SELECT {order} FROM {table} ORDER BY {order}')]
            if original != copied:
                raise ValueError(f'{table} 数据逐字段校验失败，已回滚。')
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        source.close()
    return {'backup': str(snapshot), 'backup_sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest(), 'counts': counts}


def main():
    pending = DATA / 'mysql.pending.json'
    if (DATA / 'mysql.json').exists():
        raise ValueError('MySQL 配置已启用，拒绝重复导入。')
    config = json.loads(pending.read_text(encoding='utf-8'))
    result = migrate(DATA / 'equipreserve.sqlite3', config)
    (DATA / 'mysql-migration-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    save_private_json(DATA / 'mysql.json', config)
    print('迁移完成并逐字段校验通过：' + json.dumps(result['counts']))


if __name__ == '__main__':
    main()
