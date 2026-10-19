"""Manage this project's local-only MySQL instance without a system service."""
import json
import os
import subprocess
import time
from pathlib import Path

import pymysql

ROOT = Path(__file__).parent
DATA = ROOT / 'data'
RUNTIME = ROOT.parent / 'local-tools' / 'mysql' / 'mysql-8.4.9-winx64'
ADMIN_CONFIG = DATA / 'mysql-admin.json'


def save_private_json(path, value):
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')
    protect_file(path)


def protect_file(path):
    if os.name == 'nt':
        sid = subprocess.check_output(['powershell', '-NoProfile', '-Command',
            '[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value'], text=True).strip()
        subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r',
                        f'*{sid}:(F)', '*S-1-5-18:(F)'], check=True, capture_output=True)


def start_mysql():
    ini = DATA / 'mysql.ini'
    if not ini.is_file():
        raise RuntimeError('MySQL 尚未配置，请先执行安装和迁移步骤。')
    app_config = DATA / 'mysql.json'
    config = json.loads((app_config if app_config.exists() else ADMIN_CONFIG).read_text(encoding='utf-8'))
    try:
        pymysql.connect(**config).close()
        return
    except pymysql.err.OperationalError as error:
        if error.args[0] != 2003:
            raise
    with (DATA / 'mysql-console.log').open('ab') as log:
        process = subprocess.Popen([str(RUNTIME / 'bin' / 'mysqld.exe'), f'--defaults-file={ini}'],
                                   stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError('MySQL 启动失败，详见 data/mysql-server/mysql-error.log。')
        try:
            pymysql.connect(**config).close()
            return
        except pymysql.err.OperationalError:
            time.sleep(0.5)
    raise RuntimeError('MySQL 启动超时，详见 data/mysql-server/mysql-error.log。')


if __name__ == '__main__':
    start_mysql()
    print('MySQL 已就绪（127.0.0.1:3306）。')
