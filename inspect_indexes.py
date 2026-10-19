"""Generate query-plan evidence from the currently configured database."""
import argparse
from pathlib import Path
from database import configured_store

parser = argparse.ArgumentParser()
parser.add_argument('--db', help='显式指定 SQLite 数据库；默认使用平台当前配置')
args = parser.parse_args()
store = configured_store(args.db)
queries = [
    ('我的预约', 'SELECT * FROM reservation WHERE user_id=1 ORDER BY created_at DESC'),
    ('过期候选', "SELECT id FROM reservation WHERE status='CONFIRMED' AND pickup_deadline<='2026-10-17'"),
    ('时段占用', "SELECT * FROM slot_occupancy WHERE device_id=1 AND slot_start='2026-10-17'"),
    ('对象审计', 'SELECT * FROM audit_event WHERE target_id=1 ORDER BY created_at DESC'),
]
engine = 'MySQL' if store.mysql else 'SQLite'
prefix = 'EXPLAIN ' if store.mysql else 'EXPLAIN QUERY PLAN '
lines = [f'# {engine} 索引执行计划', '', '在本机当前业务数据库执行 EXPLAIN。数据量很小，优化器可能选择全表扫描；不代表大数据量性能。', '']
for name, sql in queries:
    lines.extend(['## ' + name, '', '```sql', sql, '```', '', '```text'])
    lines.extend(str(row) for row in store.query(prefix + sql))
    lines.extend(['```', ''])
lines.append('应在有代表性的数据规模下进一步分析 EXPLAIN 与实际耗时。')
Path(__file__).with_name('docs').joinpath(('MySQL索引执行计划.md' if store.mysql else '索引执行计划.md')).write_text('\n'.join(lines), encoding='utf-8')
