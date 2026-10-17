"""Interactive local account recovery; never accepts passwords as arguments."""
import getpass
import secrets
from pathlib import Path

from core import Store, password_hash


def reset_password(store, username, password):
    if len(password) < 8:
        raise ValueError('密码至少需要 8 位。')
    if not Path(store.path).is_file():
        raise ValueError('尚未初始化数据库，请先运行启动平台。')
    hashed = password_hash(password)
    db = store.connect()
    try:
        db.execute('BEGIN IMMEDIATE')
        user = db.execute('SELECT id FROM app_user WHERE username=?', (username,)).fetchone()
        if not user:
            raise ValueError('账号不存在，请检查账号名称。')
        db.execute('UPDATE app_user SET password_hash=? WHERE id=?', (hashed, user['id']))
        db.execute('DELETE FROM session WHERE user_id=?', (user['id'],))
        store.audit(db, None, 'local_password_reset', user['id'], None, None,
                    secrets.token_hex(12), '本机交互式密码重置；目标为用户 ID')
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main():
    store = Store(Path(__file__).parent / 'data' / 'equipreserve.sqlite3')
    print('本地账号密码重置：保留预约和借还记录。')
    print('演示账号：student / student2 / admin；每次只修改一个账号。')
    try:
        username = input('需要重置的账号：').strip()
        password = getpass.getpass('新密码（至少 8 位，输入不回显）：')
        confirmation = getpass.getpass('再次输入新密码：')
        if password != confirmation:
            raise ValueError('两次输入不一致，未修改密码。')
        reset_password(store, username, password)
        print('密码已更新，该账号的旧登录会话已失效，请重新登录。')
    except (ValueError, OSError) as error:
        print(f'未完成：{error}')
    except (KeyboardInterrupt, EOFError):
        print('\n已取消，未修改密码。')


if __name__ == '__main__':
    main()
