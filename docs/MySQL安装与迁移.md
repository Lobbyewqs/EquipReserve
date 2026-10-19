# MySQL 安装、迁移与使用

2026-10-19：本机安装 MySQL Community Server 8.4.9，使用 [官方 Windows ZIP 安装方式](https://dev.mysql.com/doc/refman/8.4/en/windows-choosing-package.html)。`mysqld.exe` 的 Oracle America 数字签名验证为 Valid。

## 本机使用

- 双击项目中的 `启动平台.cmd`，自动启动数据库与平台；网页为 http://127.0.0.1:8765 。
- 保留原有 `student`、`student2`、`admin` 及密码，无需重新设置。
- 双击 `重置密码.cmd` 可恢复指定平台账号密码；它会使用当前 MySQL 库。
- 双击 `备份数据库.cmd`，在 `data/backups` 生成 SQL 文件。
- MySQL 使用 `127.0.0.1:3306`，库名为 `equipreserve`，项目账号为 `equipreserve`。数据库凭据自动生成，仅保存在本机受限配置文件中。
- MySQL 安装于项目上一级的 `local-tools/mysql/mysql-8.4.9-winx64`。数据库数据、日志和配置都在项目 `data` 中。不注册 Windows 服务，也不改变系统 PATH；启动平台时自动启动它。
- 停止网页进程不会关闭 MySQL。需要关闭 MySQL 时，在停止平台后使用 `停止数据库.cmd`。

## 在另一台 Windows 电脑复现

1. 安装 Python 3.11+、Microsoft Visual C++ 2015–2022 x64 运行库。
2. 从 [MySQL 官方归档](https://downloads.mysql.com/archives/community/) 下载 `mysql-8.4.9-winx64.zip`，解压到项目上一级的 `local-tools/mysql`，确认该目录下有 `mysql-8.4.9-winx64/bin/mysqld.exe`。
3. 确认端口 3306 未被其他数据库占用。在项目目录执行：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -r requirements.txt
.venv\Scripts\python.exe setup_mysql.py
```

4. 如果有 SQLite 旧数据，将其放在 `data/equipreserve.sqlite3`。关闭所有旧版平台进程后执行：

```powershell
.venv\Scripts\python.exe migrate_mysql.py
```

迁移程序创建 SQLite 一致性快照、导入到空 MySQL 库、核对每张表每个已复制字段，成功后写入 `data/mysql.json` 激活 MySQL。目标非空时拒绝重复导入；发生错误时回滚本次数据事务。DDL 建表不在数据事务中回滚。迁移期间禁止继续向旧 SQLite 写入。

5. 全新项目没有 SQLite 数据时，可将 `data/mysql.pending.json` 复制为 `data/mysql.json`，再启动平台；首次启动会交互设置演示账号密码。

连接配置、备份、账号哈希、数据库文件和 `.venv` 已排除在 Git 之外。不要上传整个 `data` 目录。已有 MySQL 数据不可被旧 SQLite 文件覆盖；回退代码前应先备份最新 MySQL 数据并制定反向迁移。

## 数据备份

备份脚本调用 MySQL 自带的 `mysqldump --single-transaction`。凭据通过短期本地受限选项文件传递，不放入命令参数；运行完删除该文件。备份包含密码哈希与业务记录，也应妥善保管。

恢复时应先停止平台，并将 SQL 导入新建的空库，校验后再切换连接配置，避免覆盖正在使用的数据库。本次升级保留迁移前 SQLite 快照，并实际验证 SQL 备份能够恢复到隔离的临时 MySQL 库。

## 事务与限制

MySQL 使用 READ COMMITTED。幂等键占位通过唯一键插入竞争获取排他锁，已成功请求返回保存结果；业务事务按幂等键 → 设备 → 预约的顺序获取锁。过期任务同样先锁设备再锁预约。同一设备不同日期仍竞争同一行，未宣称高吞吐。

文本使用 `utf8mb4_0900_bin`，保留大小写和尾部空格差异，避免迁移后幂等键误判。时间仍为 UTC 的 ISO 字符串，业务时区仍为北京时间。

仍为本机演示 HTTP 服务；未完成 HTTPS、生产部署、生产负载和崩溃恢复验证。不自动重试数据库死锁；事务会回滚，客户端应使用原幂等键重新请求。
