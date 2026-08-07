# SAP AI Flow

SAP AI Flow 是一个面向 SAP 业务流程建模的对话式流程图工具。用户可以通过中文自然语言持续修改当前流程，服务端把指令转换为结构化 Patch，经原子校验后更新 React Flow 画布。

当前仓库是可运行的 MVP 基线，默认使用本地规则引擎，无需 API Key 即可开发和演示；切换配置后可调用 DeepSeek 的 OpenAI 兼容接口。

## 当前能力

- React Flow 业务流程画布和 Dagre 自动布局。
- 开始、结束、任务、判断和子流程五类节点。
- 文本指令增量增加、删除和改名节点。
- 服务端生成稳定 ID，支持 Patch 临时引用。
- Patch 深拷贝原子执行，失败时不改变当前图。
- 画布拖动、连线、删除、节点属性编辑。
- 撤销、重做和浏览器本地恢复。
- JSON 导入导出和全图 PNG 导出。
- 本地规则 Provider 和 DeepSeek Provider。
- FastAPI OpenAPI 文档、pytest 和 Vitest 测试。
- Docker Compose 和 GitHub Actions 基线。

完整范围、协议和四周路线图见 [IMPLEMENTATION.md](./IMPLEMENTATION.md)。

## 技术栈

- Web：React 19、TypeScript、Vite、`@xyflow/react`、Dagre、Zustand。
- API：Python 3.12、FastAPI、Pydantic 2、HTTPX。
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

未配置时保持 `AGENT_PROVIDER=local`。本地规则引擎支持以下演示指令：

- `在信用检查后增加经理审批`
- `在仓库出库前增加库存确认`
- `把仓库出库改为创建交货单`
- `删除信用检查节点`
- `创建包含订单、信用检查、出库和开票的流程`

## 测试与构建

```powershell
# 后端
Set-Location .\apps\api
..\..\.venv\Scripts\python.exe -m pytest

# 前端，在仓库根目录
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
```

自动化测试默认使用本地 Provider，不会产生模型调用费用。

## Docker Compose

在仓库根目录运行：

```powershell
docker compose -f .\deploy\docker-compose.yml up --build
```

- Web：`http://localhost:8080`
- API 健康检查：`http://localhost:8000/health/live`

Compose 默认使用本地 Provider。使用 DeepSeek 时，在启动命令所在环境或根目录 `.env` 中设置 `AGENT_PROVIDER` 和 `DEEPSEEK_API_KEY`。

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
GET  /api/v1/meta
GET  /health/live
GET  /health/ready
```

`modify` 请求必须包含 `request_id`、`current_graph` 和 `instruction`。返回值包含更新后的完整图、实际 Patch、业务告警和 Provider 指标。

## 开发原则

- LLM 只提出 Patch，不直接覆盖完整图。
- 永久节点和连线 ID 由服务端生成。
- 任一操作失败时整批 Patch 回滚。
- 布局坐标不发送给模型。
- 不记录或返回模型内部思维过程。
- 真实模型冒烟测试与确定性 CI 测试分离。
