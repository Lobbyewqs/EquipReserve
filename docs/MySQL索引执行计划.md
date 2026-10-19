# MySQL 索引执行计划

在本机当前业务数据库执行 EXPLAIN。数据量很小，优化器可能选择全表扫描；不代表大数据量性能。

## 我的预约

```sql
SELECT * FROM reservation WHERE user_id=1 ORDER BY created_at DESC
```

```text
{'id': 1, 'select_type': 'SIMPLE', 'table': 'reservation', 'partitions': None, 'type': 'ref', 'possible_keys': 'reservation_user_created', 'key': 'reservation_user_created', 'key_len': '8', 'ref': 'const', 'rows': 1, 'filtered': 100.0, 'Extra': 'Backward index scan'}
```

## 过期候选

```sql
SELECT id FROM reservation WHERE status='CONFIRMED' AND pickup_deadline<='2026-10-17'
```

```text
{'id': 1, 'select_type': 'SIMPLE', 'table': 'reservation', 'partitions': None, 'type': 'index', 'possible_keys': 'reservation_expiry', 'key': 'reservation_expiry', 'key_len': '152', 'ref': None, 'rows': 1, 'filtered': 100.0, 'Extra': 'Using where; Using index'}
```

## 时段占用

```sql
SELECT * FROM slot_occupancy WHERE device_id=1 AND slot_start='2026-10-17'
```

```text
{'id': 1, 'select_type': 'SIMPLE', 'table': None, 'partitions': None, 'type': None, 'possible_keys': None, 'key': None, 'key_len': None, 'ref': None, 'rows': None, 'filtered': None, 'Extra': 'no matching row in const table'}
```

## 对象审计

```sql
SELECT * FROM audit_event WHERE target_id=1 ORDER BY created_at DESC
```

```text
{'id': 1, 'select_type': 'SIMPLE', 'table': 'audit_event', 'partitions': None, 'type': 'ref', 'possible_keys': 'audit_target_created', 'key': 'audit_target_created', 'key_len': '9', 'ref': 'const', 'rows': 3, 'filtered': 100.0, 'Extra': 'Backward index scan'}
```

应在有代表性的数据规模下进一步分析 EXPLAIN 与实际耗时。