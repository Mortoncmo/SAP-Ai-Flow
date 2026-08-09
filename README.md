# SAP AI Flow

SAP AI Flow 是一个面向 SAP 业务流程建模的对话式流程图工具。用户可以通过中文自然语言持续修改当前流程，服务端把指令转换为结构化 Patch，经原子校验后更新 React Flow 画布。

当前仓库是可运行的 MVP 基线，默认使用本地规则引擎，无需 API Key 即可开发和演示；切换配置后可调用 DeepSeek 的 OpenAI 兼容接口。

## 当前能力

- React Flow 业务流程画布和 Dagre 自动布局。
- 开始、结束、任务、判断和子流程五类节点。
- 节点语义图标，以及可编辑、可拖放归属的横向/纵向泳道。
- 文本指令增量增加、删除和改名节点。
- 服务端生成稳定 ID，支持 Patch 临时引用。
- Patch 深拷贝原子执行，失败时不改变当前图。
- 画布拖动、连线、删除、节点属性编辑。
- 撤销、重做和浏览器本地恢复。
- JSON 导入导出和全图 PNG、SVG 导出。
- 本地规则 Provider 和 DeepSeek Provider。
- 项目级外部模型开关、调用前脱敏、本地回退和策略变更审计。
- SAP MM/P2P 元数据、受控知识检索、GAP 候选与人工决策审计。
- 项目、流程、修订、发布版本、服务端项目成员角色和 Markdown/Word 蓝图导出。
- ChromaDB 持久化知识索引、确定性字符 n-gram 向量和精确词法混合召回。
- 开发环境身份头与生产 OIDC/JWKS Bearer JWT 验证边界。
- FastAPI OpenAPI 文档、pytest 和 Vitest 测试。
- Docker Compose 和 GitHub Actions 基线。

完整范围、协议和 12 周实施计划见 [IMPLEMENTATION.md](./IMPLEMENTATION.md)。

## 技术栈

- Web：React 19、TypeScript、Vite、`@xyflow/react`、Dagre、Zustand。
- API：Python 3.12、FastAPI、Pydantic 2、HTTPX、SQLAlchemy、ChromaDB、PyJWT。
- 测试：pytest、Vitest；浏览器验收使用 Playwright CLI。
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
```

`.env` 已被 Git 忽略，API Key 不应添加到前端变量、日志或提交记录中。

即使服务端配置了 DeepSeek，新项目仍默认使用“仅本地”策略。项目管理员可在“项目成员”弹窗中显式切换为“允许调用”；启用前界面会提示数据外发，策略变化写入项目审计。项目未启用时，持久化流程修改不会调用外部 Provider，而是回退本地规则并返回 warning。发送给 DeepSeek 的流程和指令会先脱敏客户、供应商、联系人、邮箱、电话和金额等字段。

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

生产环境不会信任 `X-User-ID` 或 `X-Project-Role`。缺少 OIDC 配置时 `/health/ready` 返回 503；无项目上下文的流程修改、知识检索和 GAP 分析兼容接口在非开发环境返回 404。

## 日志与安全检查

API 为每个响应返回 `X-Request-ID`。客户端提供的请求号只接受 1 至 80 位字母、数字、点、下划线、冒号和连字符，非法值会替换为服务端随机请求号。应用日志采用单行 JSON，只记录请求号、HTTP 方法、路由模板、状态码和耗时；不记录查询字符串、请求头、认证 Token、Cookie、请求正文、完整图、Prompt 或上游异常正文。未处理异常只记录异常类型和不含局部变量的代码位置。

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

当前嵌入使用离线可重复的中英文字符 n-gram 哈希向量，并与精确词法分数混合排序，不下载外部模型。开发环境允许检索待顾问审核的项目种子并保持“待确认”标识；生产环境只索引授权且 `review_status=approved` 的知识。正式发布仍需顾问标注集和语义模型对比评估。

## 测试与构建

```powershell
# 后端
Set-Location .\apps\api
..\..\.venv\Scripts\python.exe -m pytest

# 前端，在仓库根目录
npm.cmd test
npm.cmd run typecheck
npm.cmd run build

# 浏览器 smoke；需先启动 API 和 Web
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\browser_smoke.ps1
```

自动化测试默认使用本地 Provider，不会产生模型调用费用。浏览器 smoke 使用独立 Playwright CLI 会话，验证按钮和自然语言泳道操作不会增加流程节点、390 x 844 无横向溢出且控制台无错误；临时浏览器产物位于已忽略的 `.playwright-cli` 目录。

## Docker Compose

在仓库根目录运行：

```powershell
docker compose -f .\deploy\docker-compose.yml up --build
```

- Web：`http://localhost:8080`
- API 健康检查：`http://localhost:8000/health/live`

Compose 默认使用本地 Provider。使用 DeepSeek 时，在启动命令所在环境或根目录 `.env` 中设置 `AGENT_PROVIDER` 和 `DEEPSEEK_API_KEY`。

Compose 以 `APP_ENV=production` 启动 API，因此还必须在根目录 `.env` 中提供上节列出的后端 `OIDC_ISSUER`、`OIDC_AUDIENCE`、`OIDC_JWKS_URL`，以及前端 `VITE_OIDC_AUTHORITY`、`VITE_OIDC_CLIENT_ID` 和 `VITE_OIDC_AUDIENCE`。未配置时 API readiness 会保持未就绪，Web 服务不会被视为可交付状态。

PostgreSQL 数据和 ChromaDB 索引分别持久化到 `postgres-data` 与 `chroma-data` 命名卷。

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
