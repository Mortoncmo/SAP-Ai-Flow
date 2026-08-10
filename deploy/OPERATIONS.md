# 部署与恢复操作

本文档面向 `deploy/docker-compose.yml` 的内部部署。备份文件包含项目流程、修订、审计记录和知识索引，必须放在受控存储中，不要上传到 GitHub 或聊天工具。

Compose 不提供 PostgreSQL 默认密码。启动前必须在根目录 `.env` 设置 URL 安全的强 `POSTGRES_PASSWORD`，并配置目标 OIDC；不要把生产 `.env` 加入镜像、备份归档或 Git。

## 启动与迁移

```powershell
docker compose -f .\deploy\docker-compose.yml up -d postgres
docker compose -f .\deploy\docker-compose.yml run --rm api alembic upgrade head
docker compose -f .\deploy\docker-compose.yml up -d api worker web
Invoke-WebRequest http://localhost:8080/health/ready
```

通过 Web 入口访问 `/health/ready`；它会检查认证/Provider/导出执行模式并实际执行数据库连接查询。只有返回 `200`、`status=ok`、`database=ready` 且 `export_execution=worker` 后才允许写入项目。再运行 `docker compose -f .\deploy\docker-compose.yml ps`，确认 PostgreSQL、API、Worker 和 Web 都为健康状态。API 的 8000 端口仅在 Compose 网络内暴露，不应绕过 Nginx 直接发布到宿主机或外部负载均衡器。

## 外部模型调用缓存

项目管理员明确开启外部模型后，持久化流程修改可复用短时间内完全相同的成功 Provider 结果。部署时显式配置：

```dotenv
LLM_CACHE_TTL_SECONDS=60
LLM_CACHE_MAX_ENTRIES=128
```

- 任一值设为 `0` 即关闭缓存；调整后需要重启 API 进程。
- 缓存按项目/流程命名空间、Provider/模型、当前图、指令、语言和知识证据隔离，只保存结构化 Provider 结果，不保存完整 API 响应、修订号或 ChangeLog。
- 本地规则 Provider、外部模型未授权的项目、无状态兼容接口、Provider 异常和被取消的上游任务不写入缓存。
- 相同键的并发请求在单个事件循环内合并。API 响应通过 `cache_status=bypassed|miss|hit|shared` 和 `model_calls=0|1` 暴露本次调用情况。
- 命中结果仍重新执行证据验证、原子 Patch、项目权限、`base_revision` 冲突检查和数据库事务。缓存丢失或多实例未共享只影响命中率，不得影响流程正确性。
- 缓存位于单个 API 进程内，进程重启即清空，多实例之间不共享。目标环境必须结合真实外部模型/PostgreSQL 压测决定继续单实例低并发、引入分布式缓存或仅调整 TTL/容量；当前实现不能作为多实例容量结论。

若怀疑短期结果复用影响排障，可先把任一缓存配置设为 `0` 并滚动重启 API，再使用同一修订重试；不要直接修改流程修订或缓存代码绕过证据和事务校验。恢复配置前记录 `request_id`、`cache_status`、`model_calls`、Provider/模型和流程修订，禁止记录 Prompt、完整图或客户业务数据。

## 外部模型与 PostgreSQL 容量验收

正式容量测试会创建一个项目和每样本一个独立流程，不自动删除数据，并可能产生付费模型调用。运行前必须确认维护窗口、Provider 配额/费用、目标数据库备份空间和测试数据处置方式；使用具备 `project_admin` 权限的受控 OIDC Token，不得使用开发身份头测试远程环境。

```powershell
$env:SAP_FLOW_ACCESS_TOKEN = '<injected-secret>'
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_capacity_test.ps1 `
  -BaseUrl https://sap-flow.example.com `
  -AllowDataCreation `
  -EnableExternalModel `
  -RequireExternalProvider `
  -RequirePostgreSQL
```

默认运行 1、2、4、8 四档并发，每档 20 个独立样本；默认门槛为错误率不高于 1%、P95 不高于 8 秒、P99 不高于 15 秒。需要调整时显式传入 `-ConcurrencyLevels`、`-SamplesPerLevel`、`-MaxErrorRatePercent`、`-MaxP95Ms` 和 `-MaxP99Ms`，并在验收记录中说明依据，不能为了通过而事后放宽门槛。

脚本先读取 `/health/ready` 的 `database_backend`，`-RequirePostgreSQL` 会在创建测试项目之前拒绝 SQLite；`-RequireExternalProvider` 会把本地回退或没有产生外部模型调用的成功响应记为失败。报告保存每档错误率、P50/P95/P99、Provider/模型、调用次数和缓存状态，不保存 Token、Prompt、指令或完整图。归档时至少保留 JSON、CSV、Git 提交 SHA、目标部署版本、Provider 配额和运行窗口；只有 `database_backend=postgresql`、两个外部模型布尔标志为 `true` 且所有并发级别通过，才可关闭 Week 11 容量门槛。

容量场景按流程隔离，因此适合测量外部模型与 PostgreSQL 的并发和长尾，不代表真实业务缓存命中率。缓存命中率必须结合目标工作负载和应用响应指标单独评估，再决定 TTL/容量、分布式缓存或单实例限制。

## 异步导出保留与恢复

Markdown/Word 导出通过持久化 `export_job` 记录状态和临时文件内容。部署时显式配置：

```dotenv
EXPORT_RETENTION_HOURS=24
EXPORT_STALE_MINUTES=5
EXPORT_LEASE_HEARTBEAT_SECONDS=30
EXPORT_EXECUTION_MODE=worker
EXPORT_WORKER_POLL_SECONDS=1
EXPORT_WORKER_BATCH_SIZE=8
```

- Web 创建任务后轮询 `pending | running`，仅在 `completed` 时下载；`failed` 和 `expired` 必须重新创建任务。
- 生产 API 只创建和查询任务，不执行文档渲染；独立 Worker 轮询 `pending` 和超过陈旧阈值的 `running` 任务。非开发环境配置为 `inline` 时 readiness 返回 503。
- Worker 领取任务时原子生成 `claim_token`、递增 `attempt_count` 并写入 `heartbeat_at`。渲染期间由独立数据库会话按心跳间隔续租；心跳间隔必须不超过陈旧窗口的三分之一。完成或失败写回必须匹配当前 Token；旧 Worker 被新实例接管后不能覆盖新结果。
- 陈旧判定优先使用 `heartbeat_at`，兼容迁移前只有 `started_at` 的运行任务。只有心跳和开始时间都超过陈旧窗口才允许重新领取，正常长文档不会因渲染时间超过五分钟而重复执行。
- Worker 每轮都会把到期任务转为 `expired` 并清空二进制内容。低流量实例也会按轮询周期清理，但仍必须监控 `export_job` 表容量、失败率、陈旧接管次数和平均渲染时长。
- 可以启动多个 Worker；目标业务负载下的并发吞吐、进程滚动重启、五分钟以上长文档和批量上限仍必须在目标 PostgreSQL 环境验证后才能确定实例数、轮询周期和陈旧阈值。
- GitHub Compose 基线已具备扩容到两个健康 Worker 的验收脚本；本轮 CI 将以 12 个普通任务验证 `attempt_count=1`，以 1 个预置陈旧任务验证 `attempt_count=2` 和旧 Token 写回拒绝，再以开始时间已旧但心跳新鲜的任务验证不会被接管。该门禁证明租约正确性，不替代目标工作负载的吞吐量和长文档中断恢复结论。
- Worker 结构化日志只允许记录 `export_id`、尝试次数、结果和异常类型，不得记录蓝图正文、Prompt、认证信息或客户业务数据。
- 应用数据库只保存短期下载内容，不是永久文档库。正式蓝图下载后必须转存到有权限、保留期和备份策略的受控文档库。

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

恢复会覆盖数据库或索引，必须在变更窗口执行，并由项目负责人确认备份文件的 SHA256。恢复前先停止 API 和 Worker，保留当前卷快照，再恢复数据库和 Chroma，最后运行迁移和 readiness 检查。

```powershell
# 1. 明确确认后才执行
$confirmRestore = Read-Host '输入 RESTORE 以继续恢复'
if ($confirmRestore -cne 'RESTORE') { throw '已取消恢复' }

docker compose -f .\deploy\docker-compose.yml stop web worker api

# 2. 恢复 SQL（文件必须来自受控备份目录）
Get-Content -LiteralPath .\output\backups\postgres-YYYYMMDD-HHmmss.sql -Raw -Encoding utf8 |
  docker compose -f .\deploy\docker-compose.yml exec -T postgres `
    psql --username $dbUser --dbname $dbName --set ON_ERROR_STOP=on

# 3. 恢复 Chroma 前确认卷名和归档校验和，然后覆盖目标卷
docker run --rm -v "${volume}:/target" -v "${backupDir}:/backup:ro" alpine `
  sh -c 'rm -rf /target/* && tar xzf /backup/chroma-YYYYMMDD-HHmmss.tar.gz -C /target'

# 4. 迁移、启动和健康检查
docker compose -f .\deploy\docker-compose.yml run --rm api alembic upgrade head
docker compose -f .\deploy\docker-compose.yml up -d api worker web
Invoke-WebRequest http://localhost:8080/health/ready
```

恢复后必须抽查：项目成员角色、最新修订号、发布版本不可变性、ChangeLog/GAP 决策数量、知识检索来源版本、外部模型开关，以及未过期导出任务的状态与下载。若 readiness 未通过，禁止把 Web 入口交给业务用户。

## 故障排查

先记录失败时间、环境、`X-Request-ID`/响应 `request_id`、流程 ID 和修订号。日志可以记录这些定位字段，但不得粘贴认证头、Cookie、模型 API Key、请求正文或客户业务数据。

| 现象或错误码 | 首要检查 | 处理原则 |
| --- | --- | --- |
| `/health/ready` 返回 503 | `APP_ENV`、OIDC/JWKS、Provider、`EXPORT_EXECUTION_MODE=worker` 和数据库连接 | readiness 恢复前停止业务写入，不绕过生产认证或导出执行门禁 |
| `DATABASE_WRITE_FAILED` | PostgreSQL 容器状态、连接数、磁盘、账号权限和 API 同请求号日志 | 确认事务已回滚；不要手工递增修订号，修复后重试原操作 |
| `REVISION_CONFLICT` | 当前流程最新修订和客户端 `base_revision` | 先导出本地 JSON，再重新打开最新修订；不得静默覆盖 |
| `KNOWLEDGE_UNAVAILABLE` | Chroma 卷、知识目录权限、索引版本和 API 日志 | 保留当前图；恢复索引后重试，不把无证据专业字段改为已验证 |
| `PROVIDER_TIMEOUT` / `PROVIDER_UNAVAILABLE` | 外部模型策略、网络、限流、Provider 总时限 | 不应用迟到响应；确认当前修订未变化后重试或切回本地 Provider |
| `RELEASE_PREFLIGHT_FAILED` | 响应中的缺失字段、上下文不一致、证据和 GAP 审计清单 | 补齐数据或顾问决策，不直接修改数据库绕过发布检查 |
| `EXPORT_NOT_READY` | `export_id` 状态、Worker 健康、任务开始时间和 `attempt_count` | 保持轮询并检查 Worker 日志；超过陈旧阈值后由 Worker 自动接管，不直接修改任务状态 |
| `EXPORT_RENDER_FAILED` | Worker 内存、流程图完整性、字体、`export_id` 和结构化任务日志 | 当前图和修订保持可用；修复环境后创建新任务，不复用失败文件 |
| `EXPORT_EXPIRED` | `expires_at`、保留配置和数据库时间 | 对同一修订创建新任务；正式交付物应从受控文档库获取 |

建议按顺序收集只读诊断信息：

```powershell
docker compose -f .\deploy\docker-compose.yml ps
docker compose -f .\deploy\docker-compose.yml logs --since 15m api worker postgres
docker compose -f .\deploy\docker-compose.yml exec -T postgres pg_isready
docker compose -f .\deploy\docker-compose.yml run --rm api alembic current
Invoke-WebRequest -UseBasicParsing http://localhost:8080/health/live
Invoke-WebRequest -UseBasicParsing http://localhost:8080/health/ready
```

恢复服务后通过受控 Secret 注入设置 `SAP_FLOW_ACCESS_TOKEN`，再执行 `scripts/run_acceptance_demo.ps1 -BaseUrl http://localhost:8080`，确认项目创建、两轮修改、发布、两个 `export_id` 完成和 Markdown/Word 下载全部成功。Token 不得出现在命令历史归档、日志或验收摘要中；生产故障期间生成的日志、数据库备份和验收摘要必须进入受控交付记录，不提交到 GitHub。

## SQLite 开发数据

开发环境没有 Docker 时，先停止 API，再复制 `output/sap_blueprint.db` 到受控备份目录。恢复时保留当前文件副本后覆盖，并运行 `apps/api` 下的 Alembic 升级/回滚测试；SQLite 备份不替代生产 PostgreSQL 备份。

## 当前验收边界

本机没有 Docker CLI，因此 Compose build/up、真实 PostgreSQL、卷归档和恢复尚未完成本机实跑。目标环境需按本文档执行卷归档、恢复、长文档滚动中断和容量演练，并归档命令输出、SHA256、readiness 与导出验收结果；GitHub Actions 的最新运行号和迁移头以 PR 检查为准。
