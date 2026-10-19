"""One-time local MySQL configuration; never prints generated credentials."""
import json
import secrets
import subprocess

import pymysql

from mysql_local import ADMIN_CONFIG, DATA, RUNTIME, save_private_json, start_mysql


def main():
    DATA.mkdir(exist_ok=True)
    server_data = DATA / 'mysql-server'
    ini = DATA / 'mysql.ini'
    if ADMIN_CONFIG.exists():
        start_mysql()
        print('本地 MySQL 已配置，未重新初始化。')
        return
    if server_data.exists():
        raise RuntimeError('MySQL 数据目录已存在，拒绝覆盖；请检查之前的安装状态。')
    ini.write_text('[mysqld]\n'
                   f'basedir={RUNTIME.as_posix()}\n'
                   f'datadir={server_data.as_posix()}\n'
                   'bind-address=127.0.0.1\nport=3306\nmysqlx=0\n'
                   'character-set-server=utf8mb4\ncollation-server=utf8mb4_0900_bin\n'
                   'max-connections=200\ninnodb-buffer-pool-size=128M\n'
                   'log-error=mysql-error.log\n', encoding='utf-8')
    subprocess.run([str(RUNTIME / 'bin' / 'mysqld.exe'), f'--defaults-file={ini}',
                    '--initialize-insecure'], check=True, capture_output=True)
    # Bootstrap only binds loopback; set the generated root password immediately.
    initial = {'host': '127.0.0.1', 'port': 3306, 'user': 'root', 'password': ''}
    save_private_json(ADMIN_CONFIG, initial)
    start_mysql()
    root_password = secrets.token_urlsafe(36)
    app_password = secrets.token_urlsafe(36)
    connection = pymysql.connect(**initial, autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute('ALTER USER CURRENT_USER() IDENTIFIED BY %s', (root_password,))
            initial['password'] = root_password
            save_private_json(ADMIN_CONFIG, initial)
            cursor.execute('CREATE DATABASE equipreserve CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin')
            cursor.execute("CREATE USER 'equipreserve'@'localhost' IDENTIFIED BY %s", (app_password,))
            cursor.execute("GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,ALTER,INDEX,REFERENCES ON equipreserve.* TO 'equipreserve'@'localhost'")
        # Activate this config only after the migration has been verified.
        save_private_json(DATA / 'mysql.pending.json', {
            'host': '127.0.0.1', 'port': 3306, 'user': 'equipreserve',
            'password': app_password, 'database': 'equipreserve'})
    finally:
        connection.close()
    print('MySQL 本地实例和项目专用账号已配置，凭据保存在受限的 data 目录配置中。')


if __name__ == '__main__':
    main()
