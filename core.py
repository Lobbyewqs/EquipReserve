"""Equipment transactions: SQLite writer serialization or MySQL device row locks."""
import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
SHANGHAI = timezone(timedelta(hours=8))


def stamp(value):
    return value.astimezone(UTC).isoformat(timespec='seconds')


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600_000).hex()
    return f'{salt}${digest}'


class BusinessError(Exception):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class Store:
    def __init__(self, path, clock=None, fault=None):
        self.mysql = isinstance(path, dict)
        self.path = dict(path) if self.mysql else str(path)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.fault = fault

    def connect(self):
        if self.mysql:
            from database import MySQLConnection
            return MySQLConnection(self.path)
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=30000')
        return db

    def initialize(self):
        if self.mysql:
            db = self.connect()
            try:
                for sql in Path(__file__).with_name('schema_mysql.sql').read_text(encoding='utf-8').split(';'):
                    if sql.strip():
                        db.execute(sql)
                if not db.execute("SELECT 1 FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME='device' AND CONSTRAINT_NAME='device_current_loan'").fetchone():
                    db.execute('ALTER TABLE device ADD CONSTRAINT device_current_loan FOREIGN KEY(current_loan_id) REFERENCES reservation(id)')
            finally:
                db.close()
            return
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        db = self.connect()
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))
            db.execute('BEGIN IMMEDIATE')
            if 'deleted_at' not in {row['name'] for row in db.execute('PRAGMA table_info(device)')}:
                db.execute('ALTER TABLE device ADD COLUMN deleted_at TEXT')
            db.execute('PRAGMA user_version=2')
            db.commit()
        finally:
            db.close()

    def seed(self, password):
        hashed = password_hash(password)
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            for name, role in [('student', 'USER'), ('student2', 'USER'), ('admin', 'ADMIN')]:
                db.execute('INSERT OR IGNORE INTO app_user(username,password_hash,role) VALUES(?,?,?)', (name, hashed, role))
            for code, name, category, desc in [
                ('CAM-001', '索尼 A6400', '影像设备', '社团活动、采访与日常影像记录。含镜头、电池和收纳包。'),
                ('CAM-002', '佳能 EOS R50', '影像设备', '轻量微单相机，适合摄影入门与视频拍摄。'),
                ('DEV-001', '树莓派开发套件', '开发硬件', '用于课程实验与原型开发，含电源及基础配件。'),
                ('AUD-001', '无线领夹麦克风', '音频设备', '双人收音套装，适合讲座、访谈和短视频。'),
                ('DEV-002', 'Arduino 实验箱', '开发硬件', '开发板与传感器套件，适合电子制作入门。'),
                ('PRO-001', '便携投影仪', '演示设备', '用于社团会议与课堂展示，含 HDMI 线缆。'),
            ]:
                db.execute('INSERT OR IGNORE INTO device(asset_code,name,category,description) VALUES(?,?,?,?)', (code, name, category, desc))
            db.commit()
        finally:
            db.close()

    def query(self, sql, args=()):
        db = self.connect()
        try:
            return [dict(row) for row in db.execute(sql, args)]
        finally:
            db.close()

    def locked(self, db, sql, args=()):
        return db.execute(sql + (' FOR UPDATE' if self.mysql else ''), args).fetchone()

    def lock_device(self, db, device_id):
        return self.locked(db, 'SELECT * FROM device WHERE id=?', (device_id,))

    def lock_reservation(self, db, reservation_id):
        # device_id is immutable. Discover it before taking device -> reservation locks.
        row = db.execute('SELECT device_id FROM reservation WHERE id=?', (reservation_id,)).fetchone()
        if not row:
            return None, None
        device = self.lock_device(db, row['device_id'])
        return self.locked(db, 'SELECT * FROM reservation WHERE id=?', (reservation_id,)), device

    def audit(self, db, actor, action, target, before, after, request_id, reason=None):
        db.execute('INSERT INTO audit_event(actor_id,action,target_id,before_state,after_state,reason,request_id,created_at) VALUES(?,?,?,?,?,?,?,?)',
                   (actor, action, target, before, after, reason, request_id, stamp(self.clock())))

    def login(self, username, password):
        users = self.query('SELECT * FROM app_user WHERE username=? AND enabled=1', (username,))
        # Use the same slow hash even when the account does not exist.
        saved = users[0]['password_hash'] if users else '00' * 16 + '$' + '00' * 32
        if not hmac.compare_digest(password_hash(password, saved.split('$')[0]), saved) or not users:
            raise BusinessError('LOGIN_FAILED', '账号或密码错误', 401)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        user = users[0]
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM session WHERE expires_at<=?', (stamp(self.clock()),))
            db.execute('INSERT INTO session VALUES(?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user['id'], csrf, stamp(self.clock() + timedelta(hours=8))))
            db.commit()
        finally:
            db.close()
        return token, {'id': user['id'], 'username': user['username'], 'role': user['role'], 'csrf': csrf}

    def authenticate(self, token):
        rows = self.query('SELECT u.id,u.username,u.role,s.csrf FROM session s JOIN app_user u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1',
                          (hashlib.sha256(token.encode()).hexdigest(), stamp(self.clock())))
        if not rows:
            raise BusinessError('UNAUTHORIZED', '请先登录', 401)
        return rows[0]

    def logout(self, token):
        db = self.connect()
        try:
            db.execute('DELETE FROM session WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
        finally:
            db.close()

    @staticmethod
    def admin(actor):
        if actor['role'] != 'ADMIN':
            raise BusinessError('FORBIDDEN', '此操作仅限管理员', 403)

    def slot_times(self):
        today = self.clock().astimezone(SHANGHAI).date()
        for day in range(14):
            date = today + timedelta(days=day)
            for start, end in [(9, 12), (14, 18)]:
                begin = datetime(date.year, date.month, date.day, start, tzinfo=SHANGHAI)
                yield stamp(begin), stamp(begin.replace(hour=end)), stamp(begin + timedelta(minutes=15))

    def slots(self, device_id):
        devices = self.query('SELECT * FROM device WHERE id=? AND deleted_at IS NULL', (device_id,))
        if not devices:
            raise BusinessError('NOT_FOUND', '设备不存在', 404)
        device = devices[0]
        occupied = {r['slot_start'] for r in self.query('SELECT slot_start FROM slot_occupancy WHERE device_id=?', (device_id,))}
        now = stamp(self.clock())
        result = []
        for start, end, deadline in self.slot_times():
            reason = '设备已停用' if not device['enabled'] else '预约已截止' if start <= now else '该时段已被预约' if start in occupied else None
            result.append({'slotStart': start, 'slotEnd': end, 'pickupDeadline': deadline, 'available': reason is None, 'reason': reason})
        return {'device': device, 'slots': result}

    def reservations(self, actor, all_users=False):
        if all_users:
            self.admin(actor)
        rows = self.query('SELECT r.*,d.name,d.asset_code,d.enabled,d.current_loan_id,u.username FROM reservation r JOIN device d ON d.id=r.device_id JOIN app_user u ON u.id=r.user_id ' +
                          ('' if all_users else 'WHERE r.user_id=? ') + 'ORDER BY r.created_at DESC,r.id DESC LIMIT 500', () if all_users else (actor['id'],))
        now = stamp(self.clock())
        for row in rows:
            row['overdue'] = row['status'] == 'BORROWED' and now > row['slot_end']
            row['exception'] = '设备已停用' if not row['enabled'] else '上一笔借用未归还' if row['status'] == 'CONFIRMED' and row['current_loan_id'] else None
        return rows

    def mutate(self, actor, operation, key, payload, target=None, request_id=None):
        request_id = request_id or secrets.token_hex(12)
        if not isinstance(key, str) or not 1 <= len(key) <= 128:
            raise BusinessError('INVALID_KEY', '写操作需要 1～128 字符的 Idempotency-Key', 400)
        if not isinstance(payload, dict):
            raise BusinessError('INVALID_BODY', '请求必须为 JSON 对象', 400)
        payload = dict(payload)
        if operation == 'reserve':
            try:
                parsed = datetime.fromisoformat(payload['slotStart'])
                if parsed.tzinfo is None or type(payload['deviceId']) is not int:
                    raise ValueError()
                payload['slotStart'] = stamp(parsed)
            except (KeyError, ValueError, TypeError):
                raise BusinessError('INVALID_SLOT', '请提供设备 ID 和带时区的时段', 400)
        digest = hashlib.sha256(json.dumps({'target': target, 'body': payload}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            if self.mysql:
                db.execute('INSERT INTO idempotency_record VALUES(?,?,?,?,?,?) ON DUPLICATE KEY UPDATE request_key=request_key',
                           (actor['id'], operation, key, digest, 'null', 0))
            old = db.execute('SELECT * FROM idempotency_record WHERE user_id=? AND operation=? AND request_key=?', (actor['id'], operation, key)).fetchone()
            if old and old['response_code']:
                if old['request_hash'] != digest:
                    raise BusinessError('KEY_CONFLICT', '幂等键已用于不同请求')
                db.commit()
                return json.loads(old['response_json']), old['response_code']
            if operation in ('checkout', 'return', 'device', 'device_create', 'device_delete'):
                self.admin(actor)
            now = stamp(self.clock())
            before = None
            if operation == 'reserve':
                device = self.lock_device(db, payload['deviceId'])
                if not device or device['deleted_at'] is not None:
                    raise BusinessError('NOT_FOUND', '设备不存在', 404)
                if not device['enabled']:
                    raise BusinessError('DEVICE_DISABLED', '设备已停用')
                valid = {s: (e, d) for s, e, d in self.slot_times()}
                start = payload['slotStart']
                if start not in valid or start <= now:
                    raise BusinessError('SLOT_CLOSED', '时段不在开放范围或预约已截止')
                if db.execute('SELECT 1 FROM slot_occupancy WHERE device_id=? AND slot_start=?', (device['id'], start)).fetchone():
                    raise BusinessError('SLOT_OCCUPIED', '该时段已被预约')
                end, deadline = valid[start]
                target = db.execute("INSERT INTO reservation(user_id,device_id,slot_start,slot_end,pickup_deadline,status,created_at) VALUES(?,?,?,?,?,'CONFIRMED',?)", (actor['id'], device['id'], start, end, deadline, now)).lastrowid
                db.execute('INSERT INTO slot_occupancy VALUES(?,?,?)', (device['id'], start, target))
                if self.fault:
                    self.fault('after_occupancy')
                after = 'CONFIRMED'
                result, status = {'id': target, 'status': after}, 201
            elif operation == 'device_create':
                fields = {'asset_code': 64, 'name': 120, 'category': 60, 'description': 1000}
                if set(payload) - fields.keys() or not {'asset_code', 'name', 'category'} <= payload.keys():
                    raise BusinessError('INVALID_DEVICE', '请填写资产编号、名称和分类', 400)
                values = {}
                for field, limit in fields.items():
                    value = payload.get(field, '')
                    if not isinstance(value, str) or len(value.strip()) > limit or (field != 'description' and not value.strip()):
                        raise BusinessError('INVALID_DEVICE', '设备字段为空、类型错误或超出长度限制', 400)
                    values[field] = value.strip()
                if db.execute('SELECT 1 FROM device WHERE asset_code=?', (values['asset_code'],)).fetchone():
                    raise BusinessError('ASSET_CODE_EXISTS', '资产编号已存在（含已删除设备），请使用唯一编号')
                target = db.execute('INSERT INTO device(asset_code,name,category,description) VALUES(?,?,?,?)',
                                    tuple(values.values())).lastrowid
                after = json.dumps(values, ensure_ascii=False)
                result, status = {'id': target, **values, 'enabled': True}, 201
            elif operation == 'device_delete':
                device = self.lock_device(db, target)
                if not device:
                    raise BusinessError('NOT_FOUND', '设备不存在', 404)
                if payload:
                    raise BusinessError('INVALID_BODY', '删除设备不接受额外参数', 400)
                if device['current_loan_id'] is not None or db.execute("SELECT 1 FROM reservation WHERE device_id=? AND status IN ('CONFIRMED','BORROWED')", (target,)).fetchone():
                    raise BusinessError('DEVICE_IN_USE', '设备有待领取预约或未归还借用，请先取消预约、等待过期或办理归还')
                before = 'DELETED' if device['deleted_at'] else 'ACTIVE'
                after = 'DELETED'
                if not device['deleted_at']:
                    db.execute('UPDATE device SET deleted_at=?,enabled=0 WHERE id=?', (now, target))
                result, status = {'id': target, 'deleted': True}, 200
            elif operation == 'device':
                device = self.lock_device(db, target)
                if not device or device['deleted_at'] is not None:
                    raise BusinessError('NOT_FOUND', '设备不存在', 404)
                if set(payload) != {'enabled'} or type(payload['enabled']) is not bool:
                    raise BusinessError('INVALID_BODY', '设备维护仅接受 enabled 布尔值', 400)
                before, after = str(device['enabled']), str(int(payload['enabled']))
                db.execute('UPDATE device SET enabled=? WHERE id=?', (int(payload['enabled']), target))
                result, status = {'id': target, 'enabled': payload['enabled']}, 200
            else:
                row, device = self.lock_reservation(db, target)
                if not row or (actor['role'] != 'ADMIN' and row['user_id'] != actor['id']):
                    raise BusinessError('NOT_FOUND', '预约不存在或不可见', 404)
                before = row['status']
                after = before
                if operation == 'cancel':
                    if before == 'CANCELLED':
                        pass
                    elif before != 'CONFIRMED' or now >= row['slot_start']:
                        raise BusinessError('CANNOT_CANCEL', '只有开始前的已确认预约可以取消')
                    else:
                        after = 'CANCELLED'
                        db.execute('DELETE FROM slot_occupancy WHERE reservation_id=?', (target,))
                elif operation == 'checkout':
                    if before != 'CONFIRMED':
                        raise BusinessError('INVALID_STATE', '当前状态不可领取')
                    if not device['enabled']:
                        raise BusinessError('DEVICE_DISABLED', '设备已停用，不能领取')
                    if not row['slot_start'] <= now < row['pickup_deadline']:
                        raise BusinessError('PICKUP_CLOSED', '不在领取窗口内（开始后 15 分钟内）')
                    if device['current_loan_id'] is not None:
                        raise BusinessError('PREVIOUS_LOAN', '上一笔借用未归还')
                    after = 'BORROWED'
                    db.execute('UPDATE device SET current_loan_id=? WHERE id=?', (target, row['device_id']))
                    db.execute('UPDATE reservation SET borrowed_at=? WHERE id=?', (now, target))
                elif operation == 'return':
                    if before == 'RETURNED':
                        pass
                    elif before != 'BORROWED' or device['current_loan_id'] != target:
                        raise BusinessError('INVALID_STATE', '当前预约与实物借用状态不一致')
                    else:
                        after = 'RETURNED'
                        db.execute('UPDATE device SET current_loan_id=NULL WHERE id=? AND current_loan_id=?', (row['device_id'], target))
                        db.execute('UPDATE reservation SET returned_at=? WHERE id=?', (now, target))
                else:
                    raise BusinessError('INVALID_OPERATION', '未知操作', 400)
                db.execute('UPDATE reservation SET status=? WHERE id=?', (after, target))
                result, status = {'id': target, 'status': after}, 200
            self.audit(db, actor['id'], operation, target, before, after, request_id)
            if self.mysql:
                db.execute('UPDATE idempotency_record SET response_json=?,response_code=? WHERE user_id=? AND operation=? AND request_key=?',
                           (json.dumps(result), status, actor['id'], operation, key))
            else:
                db.execute('INSERT INTO idempotency_record VALUES(?,?,?,?,?,?)', (actor['id'], operation, key, digest, json.dumps(result), status))
            db.commit()
            return result, status
        except Exception as error:
            db.rollback()
            if self.mysql and operation == 'device_create' and getattr(error, 'args', (None,))[0] == 1062:
                error = BusinessError('ASSET_CODE_EXISTS', '资产编号已存在（含已删除设备），请使用唯一编号')
            if isinstance(error, BusinessError):
                self.audit(db, actor['id'], operation, target, None, None, request_id, error.code + ': ' + error.message)
            raise error
        finally:
            db.close()

    def expire(self):
        candidates = self.query("SELECT id FROM reservation WHERE status='CONFIRMED' AND pickup_deadline<=?", (stamp(self.clock()),))
        count = 0
        for candidate in candidates:
            db = self.connect()
            try:
                db.execute('BEGIN IMMEDIATE')
                row, _ = self.lock_reservation(db, candidate['id'])
                if row['status'] == 'CONFIRMED' and row['pickup_deadline'] <= stamp(self.clock()):
                    db.execute("UPDATE reservation SET status='EXPIRED' WHERE id=?", (row['id'],))
                    db.execute('DELETE FROM slot_occupancy WHERE reservation_id=?', (row['id'],))
                    self.audit(db, None, 'expire', row['id'], 'CONFIRMED', 'EXPIRED', secrets.token_hex(12))
                    count += 1
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
        return count
