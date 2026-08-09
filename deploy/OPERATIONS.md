# 部署与恢复操作

本文档面向 `deploy/docker-compose.yml` 的内部部署。备份文件包含项目流程、修订、审计记录和知识索引，必须放在受控存储中，不要上传到 GitHub 或聊天工具。

## 启动与迁移

```powershell
docker compose -f .\deploy\docker-compose.yml up -d postgres
docker compose -f .\deploy\docker-compose.yml run --rm api alembic upgrade head
docker compose -f .\deploy\docker-compose.yml up -d api web
Invoke-WebRequest http://localhost:8080/health/ready
```

`/health/ready` 返回 `200` 且 `status=ok` 后才允许写入项目。生产 API 必须先配置 OIDC、数据库和 Provider 环境变量。

## PostgreSQL 备份

以下命令生成可读 SQL 备份；执行前确认 `.env` 中的数据库用户名和数据库名与 Compose 一致。

```powershell
$backupDir = Join-Path (Get-Location) 'output\backups'
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$dbBackup = Join-Path $backupDir "postgres-$stamp.sql"
$dbUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { 'sap_blueprint' }
$dbName = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { 'sap_blueprint' }

docker compose -f .\deploy\docker-compose.yml exec -T postgres `
  pg_dump --clean --if-exists --no-owner --username $dbUser --dbname $dbName `
  | Set-Content -LiteralPath $dbBackup -Encoding utf8
Get-FileHash -Algorithm SHA256 -LiteralPath $dbBackup | Format-List
```

在 Linux/macOS 上可将最后的 `Set-Content` 替换为 `tee`，保留原始 UTF-8 SQL。

## Chroma 索引归档

先获取 Compose 项目生成的实际卷名，再以只读方式归档。API 继续运行时只做一致性允许的短暂备份窗口；正式备份建议先停止 API 写入。

```powershell
$backupDir = (Resolve-Path output\backups).Path
$volume = docker volume ls --format '{{.Name}}' |
  Where-Object { $_ -like '*_chroma-data' } |
  Select-Object -First 1
if (-not $volume) { throw '找不到 Chroma 数据卷' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
docker run --rm -v "${volume}:/source:ro" -v "${backupDir}:/backup" alpine `
  tar czf "/backup/chroma-$stamp.tar.gz" -C /source .
Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $backupDir "chroma-$stamp.tar.gz") | Format-List
```

## 恢复流程

恢复会覆盖数据库或索引，必须在变更窗口执行，并由项目负责人确认备份文件的 SHA256。恢复前先停止 API，保留当前卷快照，再恢复数据库和 Chroma，最后运行迁移和 readiness 检查。

```powershell
# 1. 明确确认后才执行
$confirmRestore = Read-Host '输入 RESTORE 以继续恢复'
if ($confirmRestore -cne 'RESTORE') { throw '已取消恢复' }

docker compose -f .\deploy\docker-compose.yml stop api web

# 2. 恢复 SQL（文件必须来自受控备份目录）
Get-Content -LiteralPath .\output\backups\postgres-YYYYMMDD-HHmmss.sql -Raw -Encoding utf8 |
  docker compose -f .\deploy\docker-compose.yml exec -T postgres `
    psql --username $dbUser --dbname $dbName --set ON_ERROR_STOP=on

# 3. 恢复 Chroma 前确认卷名和归档校验和，然后覆盖目标卷
docker run --rm -v "${volume}:/target" -v "${backupDir}:/backup:ro" alpine `
  sh -c 'rm -rf /target/* && tar xzf /backup/chroma-YYYYMMDD-HHmmss.tar.gz -C /target'

# 4. 迁移、启动和健康检查
docker compose -f .\deploy\docker-compose.yml run --rm api alembic upgrade head
docker compose -f .\deploy\docker-compose.yml up -d api web
Invoke-WebRequest http://localhost:8080/health/ready
```

恢复后必须抽查：项目成员角色、最新修订号、发布版本不可变性、ChangeLog/GAP 决策数量、知识检索来源版本和外部模型开关。若 readiness 未通过，禁止把 Web 入口交给业务用户。

## SQLite 开发数据

开发环境没有 Docker 时，先停止 API，再复制 `output/sap_blueprint.db` 到受控备份目录。恢复时保留当前文件副本后覆盖，并运行 `apps/api` 下的 Alembic 升级/回滚测试；SQLite 备份不替代生产 PostgreSQL 备份。

## 当前验收边界

本机没有 Docker CLI，因此 Compose build/up、真实 PostgreSQL、卷归档和恢复尚未完成实机验收。具备 Docker 的环境必须按本文档执行一次演练，并把命令输出、SHA256 和 readiness 结果归档到交付记录。
