# SAP AI Flow

SAP AI Flow 是一个面向 SAP 业务流程建模的对话式流程图工具。用户可以通过中文自然语言持续修改当前流程，服务端把指令转换为结构化 Patch，经原子校验后更新 React Flow 画布。

当前仓库是可运行的 MVP 基线，默认使用本地规则引擎，无需 API Key 即可开发和演示；切换配置后可调用 DeepSeek 的 OpenAI 兼容接口。

## 当前能力

- React Flow 业务流程画布和 Dagre 自动布局。
- 开始、结束、任务、判断和子流程五类节点。
- 节点语义图标，以及可编辑、可拖放归属的横向/纵向泳道。
- 文本指令增改删节点、连线和泳道；连线支持条件标签修改。
- 服务端生成稳定 ID，支持 Patch 临时引用。
- Patch 深拷贝原子执行，失败时不改变当前图。
- 画布拖动、连线、删除，以及节点/连线属性 Inspector；查看者保持只读。
- 撤销、重做和浏览器本地恢复。
- JSON 导入导出和全图 PNG、SVG 导出。
- 本地规则 Provider 和 DeepSeek Provider。
- 项目级外部模型开关、调用前脱敏、本地回退和策略变更审计。
- 项目/流程隔离的外部 Provider 短期结果缓存，支持 TTL/LRU、相同并发调用合并和命中指标，命中后仍执行证据、Patch、修订和事务校验。
- SAP MM/P2P 元数据、受控知识检索、GAP 候选与人工决策审计。
- 项目、流程、修订、发布版本、服务端项目成员角色与可见变更审计，以及持久化异步 Markdown/Word 蓝图导出。
- ChromaDB 持久化知识索引、确定性字符 n-gram 向量和精确词法混合召回。
- LangGraph 请求级条件编排：泳道、连线、图标和布局等纯结构修改跳过知识检索；SAP 专业修改进入检索、证据、Provider、原子 Patch 和待确认分支，文档导出执行待确认预检。
- 开发环境身份头与生产 OIDC/JWKS Bearer JWT 验证边界。
- FastAPI OpenAPI 文档、pytest 和 Vitest 测试。
- 可配置的 API 容量测试脚本，按并发级别输出错误率、P50/P95/P99、模型调用数、缓存状态和数据库后端证据。
- Docker Compose 和 GitHub Actions 基线。

完整范围、协议和 12 周实施计划见 [IMPLEMENTATION.md](./IMPLEMENTATION.md)。

## 技术栈

- Web：React 19、TypeScript、Vite、`@xyflow/react`、Dagre、Zustand。
- API：Python 3.12、FastAPI、Pydantic 2、LangGraph、HTTPX、SQLAlchemy、ChromaDB、PyJWT。
- 测试：pytest、Vitest；浏览器验收使用 Playwright CLI；Word 排版验收使用 LibreOffice、Poppler 和 Noto CJK。
- 部署：Docker、Docker Compose、Nginx。

## 本地开发

环境要求：Node.js 22 或更高版本、Python 3.12。

### 1. 安装前端依赖

```powershell
npm.cmd install
```

### 2. 创建 Python 环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\apps\api\requirements-dev.txt
```

### 3. 启动 API

```powershell
Set-Location .\apps\api
..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API 地址为 `http://localhost:8000`，开发环境接口文档为 `http://localhost:8000/docs`。

### 4. 启动 Web

打开另一个终端，在仓库根目录运行：

```powershell
npm.cmd run dev
```

Web 地址为 `http://localhost:5173`。Vite 会把 `/api` 和 `/health` 代理到本地 FastAPI。

## 使用 DeepSeek

复制 `.env.example` 为 `.env`，至少修改：

```dotenv
AGENT_PROVIDER=deepseek
DEEPSEEK_API_KEY=<your-api-key>
DEEPSEEK_MODEL=deepseek-chat
LLM_TIMEOUT_SECONDS=10
LLM_TOTAL_TIMEOUT_SECONDS=35
LLM_MAX_RETRIES=2
LLM_RETRY_BACKOFF_SECONDS=0.25
LLM_CACHE_TTL_SECONDS=60
LLM_CACHE_MAX_ENTRIES=128
EXPORT_RETENTION_HOURS=24
EXPORT_STALE_MINUTES=5
EXPORT_LEASE_HEARTBEAT_SECONDS=30
EXPORT_STORAGE_BACKEND=database
EXPORT_STORAGE_PATH=../../output/exports
EXPORT_S3_BUCKET=
EXPORT_S3_PREFIX=sap-blueprint-exports
EXPORT_S3_REGION=
EXPORT_S3_ENDPOINT_URL=
EXPORT_S3_ACCESS_KEY_ID=
EXPORT_S3_SECRET_ACCESS_KEY=
EXPORT_EXECUTION_MODE=inline
EXPORT_WORKER_POLL_SECONDS=1
EXPORT_WORKER_BATCH_SIZE=8
VITE_API_TIMEOUT_MS=40000
VITE_EXPORT_TIMEOUT_MS=44000
```

`.env` 已被 Git 忽略，API Key 不应添加到前端变量、日志或提交记录中。

即使服务端配置了 DeepSeek，新项目仍默认使用“仅本地”策略。项目管理员可在“项目成员”弹窗中显式切换为“允许调用”；启用前界面会提示数据外发，策略变化写入项目审计。项目未启用时，持久化流程修改不会调用外部 Provider，而是回退本地规则并返回 warning。发送给 DeepSeek 的流程和指令会先脱敏客户、供应商、联系人、邮箱、电话和金额等字段。

DeepSeek 单次请求默认 10 秒，最多重试 2 次，但整个 Provider 调用不会超过 35 秒。超时、网络错误、429、5xx 和结构化输出不合法可重试；认证错误和其他 4xx 立即失败。Web 普通 API 默认 40 秒超时，异步导出的任务创建、状态轮询和下载全过程默认 44 秒，Nginx 代理为 45 秒。超时、用户取消或修订冲突不会应用迟到响应，原修改指令会保留供重试。这些 Vite 变量会写入构建产物，调整后需要重新构建 Web。

项目已允许调用外部模型时，持久化流程修改会缓存成功的外部 Provider 结构化结果，默认保留 60 秒、最多 128 项；任一缓存配置设为 `0` 即关闭。缓存按项目、流程、Provider/模型、完整当前图、指令、语言和知识证据计算 SHA-256 键，不保存原始缓存键输入，不跨项目或流程复用。本地规则 Provider、失败结果和无状态兼容接口不缓存；相同并发请求只发起一次上游调用。响应 `metrics.cache_status` 为 `bypassed | miss | hit | shared`，`model_calls` 为 `0 | 1`，前端会显示“缓存命中”或“合并调用”。缓存命中仍重新执行证据校验、原子 Patch、`base_revision` 检查和数据库事务。

当前缓存只存在于单个 API 进程内，进程重启会清空，多实例之间不共享。它用于减少短时间重复请求，不替代真实外部模型/PostgreSQL 的并发、长尾、命中率和容量验收；生产运维边界见 [deploy/OPERATIONS.md](deploy/OPERATIONS.md)。

Markdown/Word 下载默认先创建持久化导出任务，再每 250 毫秒查询 `export_id`，完成后下载。任务覆盖 `pending`、`running`、`completed`、`failed`、`expired` 状态，并返回 `attempt_count`；文件默认保留 24 小时。运行中的 Worker 按 `EXPORT_LEASE_HEARTBEAT_SECONDS` 续租，只有心跳超过 `EXPORT_STALE_MINUTES` 才允许恢复执行；没有心跳的中断任务可被接管。同步导出 API 仍保留兼容，但 Web 不再使用。

开发环境默认 `EXPORT_EXECUTION_MODE=inline` 和 `EXPORT_STORAGE_BACKEND=database`，便于用 SQLite 单进程运行；生产 Compose 固定使用独立 Worker 和 `EXPORT_STORAGE_BACKEND=filesystem`，API 只创建和查询任务，导出二进制写入与数据库分离的 `export-data` 受控卷。也可以将生产后端切换为 `s3`，通过 S3 兼容对象存储保存对象并使用 AES-256 服务端加密；生产配置为 `database` 时 readiness 返回 503。Worker 使用 PostgreSQL 原子领取、心跳续租、租约 Token 栅栏和尝试次数，既避免正常长文档被误接管，也防止陈旧实例覆盖接管后的结果。CI 已用两个健康 Worker 验证 12 个普通任务恰好执行一次、对象不写入数据库、陈旧任务只接管一次、心跳新鲜任务不被接管且旧 Token 写回被拒绝。文件默认保留 24 小时并按 SHA-256 校验，正式蓝图仍需按运维策略进入受控文档库或对象存储生命周期，详见 [deploy/OPERATIONS.md](deploy/OPERATIONS.md)。

CI 还会创建 80 节点 DOCX 长任务，在心跳已推进后强制终止执行容器，等待租约真实过期，再由新 Worker 以第 2 次尝试完成并校验 DOCX 与文件系统交付物。受控延迟只允许 `APP_ENV=acceptance`；production 设置 `EXPORT_ACCEPTANCE_RENDER_DELAY_SECONDS` 会启动失败，不能把验收注入带入正式环境。该门禁证明进程中断恢复路径，不替代目标文档规模、资源上限和滚动发布窗口的容量演练。

目标 S3 配置完成后，从仓库根目录执行 `.\.venv\Scripts\python.exe .\scripts\verify_s3_storage.py --allow-write`。该命令会真实写入并删除一个唯一探针，校验上传/下载、SHA-256、长度、AES256、bucket 版本化、配置 prefix 的生命周期覆盖和删除后不可读，并默认把脱敏报告写入 `output/s3-acceptance/report.json`。`--allow-write` 是强制确认；版本化 bucket 的删除会产生删除标记，非当前探针版本仍需由生命周期与保留策略处理。未在目标企业 bucket 实跑并完成恢复演练前，不能据此宣称生产存储验收完成。

未配置时保持 `AGENT_PROVIDER=local`。本地规则引擎支持以下演示指令：

- `在信用检查后增加经理审批`
- `在仓库出库前增加库存确认`
- `把仓库出库改为创建交货单`
- `删除信用检查节点`
- `创建包含订单、信用检查、出库和开票的流程`
- `增加一个财务泳道`
- `增加三个泳道：销售、物流、财务`
- `把信用检查移动到财务泳道`
- `给信用检查增加盾牌图标`
- `连接开始到结束`
- `把开始到结束的连线标签改为快速通道`
- `删除开始到结束的连线`

## API 验收演示

启动 API 后，可用版本化场景清单跑通“创建项目 → Agent 生成 P2P → 修改连线 → 发布 → 下载蓝图”的完整 API 闭环：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_acceptance_demo.ps1 `
  -BaseUrl http://127.0.0.1:8000
```

脚本读取 `examples/mm-p2p-acceptance-demo.json`，显式按 UTF-8 发送和读取中文 JSON，并校验 7 个节点、6 条连线、5 条泳道、连线标签和发布状态。随后创建 Markdown、DOCX 两个异步任务，轮询完成并把两个 `export_id` 写入 `acceptance-summary.json`。三个产物默认写入 `output/acceptance-demo`；该目录已忽略，不会把运行数据提交到仓库。

本地开发默认使用 `-UserId local-user`。对启用 OIDC 的部署环境执行时，通过受控 Secret 注入设置 `SAP_FLOW_ACCESS_TOKEN`，或显式传入 `-AccessToken`；令牌只进入 `Authorization` 请求头，不写入验收摘要。不要把令牌明文写入命令历史。

## DOCX 渲染验收

Linux/CI 环境安装 LibreOffice Writer、Poppler 和 Noto CJK 后，运行代表性 MM/P2P 压力样例：

```bash
sudo apt-get install --yes --no-install-recommends libreoffice-writer poppler-utils fonts-noto-cjk
python scripts/verify_docx_render.py --output-dir output/docx-render-qa
```

脚本直接调用生产 `render_docx`，生成包含五泳道、长中文节点、SAP 证据和 GAP 长表格的 DOCX，再输出 PDF、逐页 PNG、提取文本、嵌入字体清单和 `render-report.json`。门禁检查第 2 页横向流程图、其余页面纵向、完整中文内容、Noto CJK 嵌入、页面非空和内容不触边；最终仍需人工查看全部 PNG。GitHub Actions 的 `docx-render` 作业执行同一流程并上传 `docx-render-qa` 证据。

没有 `soffice` 时可执行 `--generate-only` 验证 DOCX 结构，但该模式不生成 PDF/PNG，不能作为字体、分页或视觉验收通过的证据。

## 容量测试

`scripts/run_capacity_test.ps1` 为每个样本创建独立流程并执行一次持久化修改，避免把同一流程的预期修订冲突误算成模型容量。脚本必须显式传入 `-AllowDataCreation`；默认测试 1、2、4、8 四档并发，每档 20 个样本，因此会创建 80 个流程。启用外部模型时最多产生同等数量的付费调用，运行前必须确认测试窗口、配额和费用。

本地只验证脚本和阈值机制，不构成生产容量结论：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_capacity_test.ps1 `
  -BaseUrl http://127.0.0.1:8000 `
  -AllowDataCreation `
  -SamplesPerLevel 5
```

目标环境正式验收必须使用具备 `project_admin` 权限的 OIDC Token，并同时要求真实外部 Provider 和 PostgreSQL：

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

默认门槛为错误率不高于 1%、P95 不高于 8 秒、P99 不高于 15 秒，任一并发级别失败时脚本在保存报告后返回非零。JSON 汇总和 CSV 样本默认写入 `output/capacity-test`，包含测试项目 ID、`database_backend`、Provider/模型、成功响应报告的 `model_calls` 和 `cache_status`，不包含 Token、Prompt、指令或完整图。失败响应可能已消耗上游调用，因此汇总字段明确命名为 `reported_model_calls`，不能作为账单统计。只有报告同时满足 `database_backend=postgresql`、`external_model_enabled=true`、`external_provider_required=true` 且所有级别 `passed=true`，才能作为 Week 11 容量验收证据；仍需连同目标部署规格、Provider 配额和运行时间归档。当前独立流程场景用于容量测量，不代表真实业务缓存命中率。

## 身份认证

开发环境默认使用 `local-user`，可通过 `X-User-ID` 切换测试身份。该请求头只在 `APP_ENV=development` 时生效。

非开发环境只接受 `Authorization: Bearer <JWT>`，并通过 OIDC/JWKS 校验签名、issuer、audience、有效期和用户标识 claim：

```dotenv
APP_ENV=production
OIDC_ISSUER=https://identity.example.com
OIDC_AUDIENCE=sap-ai-flow
OIDC_JWKS_URL=https://identity.example.com/.well-known/jwks.json
OIDC_ALGORITHMS=RS256
OIDC_USER_ID_CLAIM=sub
OIDC_TENANT_ID_CLAIM=tid
OIDC_ALLOWED_TENANT_IDS=tenant-a,tenant-b
```

Web 端使用 Authorization Code + PKCE，不使用客户端密钥，认证状态和 PKCE 临时数据只保存在当前标签页的 `sessionStorage`。配置以下 Vite 变量后，页头会显示登录/退出入口，所有 API、流程修改和蓝图导出请求会自动携带当前 Access Token：

```dotenv
VITE_OIDC_AUTHORITY=https://identity.example.com
VITE_OIDC_CLIENT_ID=sap-ai-flow-web
VITE_OIDC_REDIRECT_URI=http://localhost:5173/auth/callback
VITE_OIDC_POST_LOGOUT_REDIRECT_URI=http://localhost:5173/
VITE_OIDC_SCOPE=openid profile email
VITE_OIDC_AUDIENCE=sap-ai-flow
```

`VITE_OIDC_REDIRECT_URI` 和 `VITE_OIDC_POST_LOGOUT_REDIRECT_URI` 必须与 Web 应用同源，并在身份提供方登记。开发服务器默认回调为 `http://localhost:5173/auth/callback`；Compose 默认分别使用当前 `http://localhost:8080` 源下的 `/auth/callback` 和 `/`。Vite 变量会写入前端构建产物，修改后必须重新构建 Web 镜像；其中不能放置客户端密钥或其他秘密。

Access Token 进入最后 60 秒且 IdP 已向公共 SPA 签发 Refresh Token 时，Web 使用 Refresh Token 单飞续期，并把新会话同步到页头；并发 API 请求不会重复续期。若 IdP 不允许公共客户端持有 Refresh Token，可保持默认 scope，不必增加 `offline_access`；Token 到期或受保护 API 返回 401 后，Web 会清除本地 OIDC 会话、切回登录态并禁用项目操作。续期失败或 API 401 不会自动重放写请求。企业 IdP 是否签发、轮换和撤销 Refresh Token 必须按安全策略在目标环境联调，具体步骤见 [deploy/OPERATIONS.md](deploy/OPERATIONS.md)。

`project_admin` 可在页头的项目访问弹窗中切换“成员 / 审计”标签。成员新增、角色变更、移除和外部模型策略变更均会记录操作者、时间和前后状态；成员写入与审计记录使用同一数据库事务。

生产环境不会信任 `X-User-ID`、`X-Project-Role` 或任何客户端租户头。JWT 必须同时包含用户 claim 和 `OIDC_TENANT_ID_CLAIM`（默认 `tid`），且租户必须命中 `OIDC_ALLOWED_TENANT_IDS`；项目创建时固化当前租户，跨租户项目、流程和知识资源统一隐藏为 404。缺少 OIDC 或租户 allowlist 配置时 `/health/ready` 返回 503；无项目上下文的流程修改、知识检索和 GAP 分析兼容接口在非开发环境返回 404。

## 日志与安全检查

API 为每个响应返回 `X-Request-ID`。客户端提供的请求号只接受 1 至 80 位字母、数字、点、下划线、冒号和连字符，非法值会替换为服务端随机请求号。应用日志采用单行 JSON，只记录请求号、HTTP 方法、路由模板、状态码和耗时；不记录查询字符串、请求头、认证 Token、Cookie、请求正文、完整图、Prompt 或上游异常正文。未处理异常只记录异常类型和不含局部变量的代码位置。

API 同时在容器内提供 `/internal/metrics` Prometheus 端点，指标只使用 HTTP 方法、路由模板和状态码标签，不包含项目 ID、用户、租户、查询参数或业务正文。Nginx 对该路径返回 404；同一 Compose 网络中的 Prometheus 可通过 `deploy/monitoring/prometheus.yml` 抓取，并将告警转发到 Alertmanager。可选监控演练栈使用 `docker compose -f .\deploy\docker-compose.yml --profile monitoring up -d prometheus alertmanager alert-drill-receiver` 启动，告警规则覆盖 API 不可用、API 5xx 超过 1% 和 API P95 超过 8 秒。`alert-drill-receiver` 只保存低基数告警摘要用于本地/CI 演练，生产必须替换 `alertmanager.yml` 的 webhook 为企业通知渠道。

请求校验错误不会回显 Pydantic 原始 `input` 或 `ctx`。业务 ChangeLog、GAP 评论和外部 Provider 请求继续使用同一套客户、供应商、人员、邮箱、电话、金额和认证秘密脱敏规则。

本地安全检查：

```powershell
# 仓库和前端构建产物秘密扫描
.\.venv\Scripts\python.exe .\scripts\security_scan.py --include-build

# Python 与 Node.js 生产依赖审计
Set-Location .\apps\api
$env:PYTHONUTF8='1'
..\..\.venv\Scripts\python.exe -m pip_audit -r requirements.txt --ignore-vuln PYSEC-2026-311
Set-Location ..\..
npm.cmd audit --omit=dev --audit-level=high
```

`PYSEC-2026-311` 的限定例外、不可达条件和复核日期记录在 [SECURITY.md](SECURITY.md)。如果部署 Chroma HTTP 服务、开放任意模型仓库配置或上游发布修复版，必须立即移除例外。

## 知识索引

知识文件从 `SAP_Knowledge` 解析为带来源、版本、章节和内容哈希的确定性 chunk，并同步到 ChromaDB。默认索引路径为 `output/chroma`，可通过以下变量调整：

```dotenv
KNOWLEDGE_INDEX_PATH=../../output/chroma
KNOWLEDGE_COLLECTION_NAME=sap_knowledge_v1
KNOWLEDGE_EMBEDDING_DIMENSIONS=384
```

当前嵌入使用离线可重复的中英文字符 n-gram 哈希向量，并与精确词法分数混合排序，不下载外部模型。最高候选分数低于 0.30 时整次查询返回证据不足；达到门槛后保留同一查询的相关支持证据。GAP 规则按模块、流程范围和 SAP Release 隔离。固定自动化集覆盖 13 个检索案例和 8 个 GAP 案例，包括 PP/SD 近邻负例。开发环境允许检索待顾问审核的项目种子并保持“待确认”标识；生产环境只索引授权且 `review_status=approved` 的知识。正式发布仍需顾问标注集和语义模型对比评估。

## 测试与构建

```powershell
# 后端
Set-Location .\apps\api
..\..\.venv\Scripts\python.exe -m pytest

# 前端，在仓库根目录
npm.cmd test
npm.cmd run typecheck
npm.cmd run build

# 浏览器 smoke；默认自动启动隔离的 API、Web 和 SQLite 测试库
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\browser_smoke.ps1

# 也可验收一个已经运行的环境
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\browser_smoke.ps1 -BaseUrl http://127.0.0.1:5173
```

自动化测试默认使用本地 Provider，不会产生模型调用费用。浏览器 smoke 使用独立 Playwright CLI 会话；未提供 `-BaseUrl` 时会自动分配端口，启动当前工作区代码和 `output/browser-smoke` 下的隔离 SQLite 数据库，完成后关闭进程。它验证本地撤销/重做/自动布局/刷新恢复、节点/连线/泳道增改删、连线 Inspector 与查看者只读、泳道操作不误增节点、项目成员增改删、外部模型二次确认及审计、取消/超时/修订冲突保图和重试、纯本地 Patch P95 小于 1 秒、持久化修改/发布/历史回看/新草稿、异步导出创建返回 `202`/`export_id`/`pending` 及 Markdown/Word 实际下载、1440 x 900、1024 x 768、390 x 844 无横向溢出，以及控制台和页面无错误。刷新只恢复当前图，撤销/重做栈不跨刷新保留。临时运行产物位于已忽略的 `output/browser-smoke` 和 `.playwright-cli` 目录。

## Docker Compose

Compose 使用生产模式，不提供数据库默认密码。先复制 `.env.example` 为 `.env`，至少设置目标 OIDC 配置和一个 URL 安全的强 PostgreSQL 密码：

```dotenv
POSTGRES_DB=sap_blueprint
POSTGRES_USER=sap_blueprint
POSTGRES_PASSWORD=<url-safe-strong-secret>
```

然后在仓库根目录运行：

```powershell
docker compose -f .\deploy\docker-compose.yml up --build
```

- Web：`http://localhost:8080`
- API 存活检查：`http://localhost:8080/health/live`
- API 就绪检查：`http://localhost:8080/health/ready`

Compose 默认使用本地 Provider。使用 DeepSeek 时，在启动命令所在环境或根目录 `.env` 中设置 `AGENT_PROVIDER` 和 `DEEPSEEK_API_KEY`。

Compose 以 `APP_ENV=production` 启动 API，因此还必须在根目录 `.env` 中提供上节列出的后端 `OIDC_ISSUER`、`OIDC_AUDIENCE`、`OIDC_JWKS_URL`、`OIDC_TENANT_ID_CLAIM` 和 `OIDC_ALLOWED_TENANT_IDS`，以及前端 `VITE_OIDC_AUTHORITY`、`VITE_OIDC_CLIENT_ID` 和 `VITE_OIDC_AUDIENCE`。未配置认证、租户 allowlist、Provider 或数据库不可连接时，API readiness 会返回 503，Web 服务不会被视为可交付状态。API 的 8000 端口只在 Compose 容器网络中暴露，外部请求统一经过 Nginx；若部署域名不是 `http://localhost:8080`，同时调整 `CORS_ORIGINS` 和 OIDC 回调地址。

PostgreSQL 数据、ChromaDB 索引和文件系统导出交付物分别持久化到 `postgres-data`、`chroma-data` 与 `export-data` 命名卷。使用 `EXPORT_STORAGE_BACKEND=s3` 时，导出交付物改由配置的 S3 bucket 管理，`export-data` 卷不承载正式文件。

`.dockerignore` 会从构建上下文排除 `.env`、虚拟环境、`node_modules`、输出目录和原始 Word/Markdown 说明书，防止本地秘密或无关大文件进入 Docker daemon 与镜像构建上下文。

迁移、PostgreSQL/Chroma 备份、恢复确认和 readiness 检查见 [deploy/OPERATIONS.md](deploy/OPERATIONS.md)。

## 项目结构

```text
apps/web/       React 流程图工作台
apps/api/       FastAPI、Provider、Patch 引擎和测试
deploy/         Docker Compose 与 Nginx 配置
.github/        持续集成工作流
IMPLEMENTATION.md
```

## API 示例

主要接口：

```text
POST /api/v1/flowcharts/modify
GET  /api/v1/projects
PUT  /api/v1/projects/{project_id}
GET  /api/v1/projects/{project_id}/audits
GET  /api/v1/projects/{project_id}/members
POST /api/v1/projects/{project_id}/knowledge/search
POST /api/v1/projects/{project_id}/gaps/analyze
GET  /api/v1/meta
GET  /health/live
GET  /health/ready
```

`flowcharts/modify` 是开发演示兼容接口，请求必须包含 `request_id`、`current_graph` 和 `instruction`。团队模式使用项目、流程和修订接口作为权威状态入口。

## 开发原则

- LLM 只提出 Patch，不直接覆盖完整图。
- 永久节点和连线 ID 由服务端生成。
- 任一操作失败时整批 Patch 回滚。
- 布局坐标不发送给模型。
- 不记录或返回模型内部思维过程。
- 真实模型冒烟测试与确定性 CI 测试分离。
