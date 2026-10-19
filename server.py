import argparse
import json
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from core import BusinessError, Store
from database import configured_store

ROOT = Path(__file__).parent


def make_server(store, host='127.0.0.1', port=8765):
    attempts = defaultdict(deque)
    attempt_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Never log request bodies, session cookies or passwords.
            pass

        def respond(self, status, data, cookie=None, content_type='application/json; charset=utf-8'):
            content = json.dumps(data, ensure_ascii=False).encode() if content_type.startswith('application/json') else data
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if cookie:
                self.send_header('Set-Cookie', cookie)
            self.end_headers()
            self.wfile.write(content)

        def handle_request(self):
            request_id = secrets.token_hex(12)
            try:
                path = urlsplit(self.path).path
                if self.headers.get('Host') not in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}:
                    raise BusinessError('INVALID_HOST', '只接受本地访问', 403)
                if not path.startswith('/api/'):
                    assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
                    if self.command != 'GET' or path not in assets:
                        raise BusinessError('NOT_FOUND', '页面不存在', 404)
                    filename, mime = assets[path]
                    self.respond(200, (ROOT / 'static' / filename).read_bytes(), content_type=mime)
                    return
                body = {}
                if self.command in ('POST', 'PATCH', 'DELETE'):
                    origin = self.headers.get('Origin')
                    if origin and origin != 'http://' + self.headers.get('Host', ''):
                        raise BusinessError('CSRF', '请求来源不匹配', 403)
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 <= length <= 16384:
                        raise BusinessError('BODY_TOO_LARGE', '请求过大', 400)
                    if length:
                        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                            raise BusinessError('INVALID_TYPE', '需要 application/json', 400)
                        body = json.loads(self.rfile.read(length))
                        if not isinstance(body, dict):
                            raise BusinessError('INVALID_BODY', '请求必须为对象', 400)
                if path == '/api/session' and self.command == 'POST':
                    with attempt_lock:
                        recent = attempts[self.client_address[0]]
                        while recent and recent[0] < time.monotonic() - 60:
                            recent.popleft()
                        if len(recent) >= 15:
                            raise BusinessError('RATE_LIMIT', '登录尝试过多，请一分钟后重试', 429)
                        recent.append(time.monotonic())
                    if not all(isinstance(body.get(k), str) and 0 < len(body[k]) <= 256 for k in ('username', 'password')):
                        raise BusinessError('INVALID_LOGIN', '请填写账号和密码', 400)
                    token, user = store.login(body['username'], body['password'])
                    self.respond(200, {'user': user, 'requestId': request_id}, f'equip_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800')
                    return
                cookies = SimpleCookie(self.headers.get('Cookie', ''))
                token = cookies['equip_session'].value if 'equip_session' in cookies else ''
                actor = store.authenticate(token)
                if self.command != 'GET' and not secrets.compare_digest(self.headers.get('X-CSRF-Token', ''), actor['csrf']):
                    raise BusinessError('CSRF', '会话校验失败，请刷新页面', 403)
                data, status = None, 200
                if path == '/api/session' and self.command == 'GET':
                    data = {'user': actor}
                elif path == '/api/session' and self.command == 'DELETE':
                    store.logout(token)
                    self.respond(200, {'ok': True, 'requestId': request_id}, 'equip_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
                    return
                elif path == '/api/devices' and self.command == 'GET':
                    params = parse_qs(urlsplit(self.path).query)
                    page = max(1, int(params.get('page', ['1'])[0]))
                    size = max(1, min(100, int(params.get('size', ['24'])[0])))
                    data = {'items': store.query('SELECT * FROM device WHERE deleted_at IS NULL ORDER BY id LIMIT ? OFFSET ?', (size, (page - 1) * size)), 'total': store.query('SELECT count(*) AS n FROM device WHERE deleted_at IS NULL')[0]['n']}
                elif (match := re.fullmatch(r'/api/devices/(\d+)/slots', path)) and self.command == 'GET':
                    data = store.slots(int(match[1]))
                elif path in ('/api/me/reservations', '/api/admin/reservations') and self.command == 'GET':
                    data = {'items': store.reservations(actor, '/admin/' in path)}
                elif path == '/api/admin/audit' and self.command == 'GET':
                    store.admin(actor)
                    data = {'items': store.query('SELECT a.*,u.username FROM audit_event a LEFT JOIN app_user u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 200')}
                else:
                    operation, target = None, None
                    if path == '/api/reservations' and self.command == 'POST':
                        operation = 'reserve'
                    elif path == '/api/admin/devices' and self.command == 'POST':
                        operation = 'device_create'
                    elif (match := re.fullmatch(r'/api/admin/devices/(\d+)', path)) and self.command == 'DELETE':
                        operation, target = 'device_delete', int(match[1])
                    elif (match := re.fullmatch(r'/api/reservations/(\d+)/cancel', path)) and self.command == 'POST':
                        operation, target = 'cancel', int(match[1])
                    elif (match := re.fullmatch(r'/api/admin/reservations/(\d+)/(checkout|return)', path)) and self.command == 'POST':
                        operation, target = match[2], int(match[1])
                    elif (match := re.fullmatch(r'/api/admin/devices/(\d+)', path)) and self.command == 'PATCH':
                        operation, target = 'device', int(match[1])
                    if not operation:
                        raise BusinessError('NOT_FOUND', '接口不存在', 404)
                    data, status = store.mutate(actor, operation, self.headers.get('Idempotency-Key'), body, target, request_id)
                self.respond(status, {**data, 'requestId': request_id})
            except BusinessError as error:
                self.respond(error.status, {'code': error.code, 'message': error.message, 'requestId': request_id})
            except (ValueError, TypeError, KeyError):
                self.respond(400, {'code': 'INVALID_REQUEST', 'message': '请求参数格式错误', 'requestId': request_id})
            except Exception:
                self.respond(500, {'code': 'INTERNAL_ERROR', 'message': '服务暂时出错，请使用相同请求重试', 'requestId': request_id})

        do_GET = do_POST = do_PATCH = do_DELETE = handle_request

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--db', help='显式指定 SQLite 文件；默认优先使用已配置的 MySQL')
    parser.add_argument('--open', action='store_true', help='启动后打开本地页面')
    args = parser.parse_args()
    store = configured_store(args.db)
    store.initialize()
    if not store.query('SELECT id FROM app_user LIMIT 1'):
        import getpass
        password = getpass.getpass('首次初始化：设置本地演示账号共用密码（至少 8 位）：')
        if len(password) < 8:
            parser.error('密码至少 8 位')
        store.seed(password)
    store.expire()
    stop = threading.Event()

    def sweep():
        while not stop.wait(60):
            try:
                store.expire()
            except Exception:
                print('过期扫描失败，将在下一分钟重试。', flush=True)

    threading.Thread(target=sweep, daemon=True).start()
    server = make_server(store, port=args.port)
    print(f'EquipReserve: http://127.0.0.1:{args.port}', flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{args.port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == '__main__':
    main()
