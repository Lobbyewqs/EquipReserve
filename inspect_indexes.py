"""Generate reproducible SQLite query-plan evidence for an initialized database."""
import argparse
from pathlib import Path
from core import Store

parser = argparse.ArgumentParser()
parser.add_argument('--db', default='data/equipreserve.sqlite3')
args = parser.parse_args()
store = Store(args.db)
queries = [
    ('我的预约', 'SELECT * FROM reservation WHERE user_id=1 ORDER BY created_at DESC'),
    ('过期候选', "SELECT id FROM reservation WHERE status='CONFIRMED' AND pickup_deadline<='2026-10-17'"),
    ('时段占用', "SELECT * FROM slot_occupancy WHERE device_id=1 AND slot_start='2026-10-17'"),
    ('对象审计', 'SELECT * FROM audit_event WHERE target_id=1 ORDER BY created_at DESC'),
]
lines = ['# SQLite 索引执行计划', '', '2026-10-17：在空业务数据的本地库执行 EXPLAIN QUERY PLAN，仅验证查询路径，不代表大数据量性能。', '']
for name, sql in queries:
    lines.extend(['## ' + name, '', '```sql', sql, '```', '', '```text'])
    lines.extend(str(tuple(row.values())) for row in store.query('EXPLAIN QUERY PLAN ' + sql))
    lines.extend(['```', ''])
lines.append('应在 MySQL 版本和有代表性的数据规模下重新分析 EXPLAIN 与实际耗时。')
Path(__file__).with_name('docs').joinpath('索引执行计划.md').write_text('\n'.join(lines), encoding='utf-8')
