"""Produce a consistent SQL backup without exposing credentials in command arguments."""
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from database import CONFIG
from mysql_local import DATA, RUNTIME, protect_file, start_mysql


def backup_mysql():
    start_mysql()
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    folder = DATA / 'backups'
    folder.mkdir(exist_ok=True)
    destination = folder / ('mysql-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.sql')
    option_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cnf', dir=DATA,
                                         encoding='utf-8', delete=False) as options:
            option_path = Path(options.name)
            for key in ('host', 'port', 'user', 'password'):
                if key == 'host':
                    options.write('[client]\n')
                escaped = str(config[key]).replace('\\', '\\\\').replace('"', '\\"')
                options.write(f'{key}="{escaped}"\n')
        protect_file(option_path)
        with destination.open('wb') as output:
            subprocess.run([str(RUNTIME / 'bin' / 'mysqldump.exe'),
                            f'--defaults-extra-file={option_path}', '--single-transaction',
                            '--no-tablespaces', '--set-gtid-purged=OFF', '--hex-blob',
                            '--column-statistics=0', '--default-character-set=utf8mb4',
                            config['database']], stdout=output, stderr=subprocess.PIPE, check=True)
        protect_file(destination)
        return destination
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        if option_path is not None:
            option_path.unlink(missing_ok=True)


if __name__ == '__main__':
    print('备份完成：' + str(backup_mysql()))
