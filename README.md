# BI Wiki Service

面向 Ontology / NL2Ontology 的独立服务项目。当前完成范围是阶段 1：FastAPI、配置、健康检查和
PostgreSQL 任务持久化。模型工作流、知识写入、审批执行与队列留待后续阶段。已增加 MOA 认证，前端登录壳位于独立 bi_wiki_web 项目。

## 目录

```text
bi_wiki/
  knowledge/{inbox,raw,wiki,schemas,templates}/
  src/bi_wiki/{api,core,db,models,repositories}/
  tests/
  docs/Agent_Service_Master_Specification.md
  docs/PROJECT_MEMORY.md
  pyproject.toml
  uv.lock
  .env.example
```

## 安装

需要 Python 3.12+ 和 PostgreSQL。以下命令从项目根目录执行：

```bash
uv sync --extra dev --locked
cp .env.example .env
```

如果已有本地 .env，请保留它。填写运行库和单独测试库的连接，不要提交真实凭据。
不使用 uv 时可使用 `python -m pip install -e '.[dev]'`，但推荐 uv 以复现锁定版本。
数据库 URL 无默认值，服务不会猜测或读取旧 BI-WIKI 项目的连接。

本地复用现有 `metadata-kb-postgres`（`127.0.0.1:5432`），无需新建 PostgreSQL 容器或镜像。
本项目使用专用非超级用户角色 `bi_wiki`，运行库 `bi_wiki`、测试库 `bi_wiki_test`。
这些库与旧项目的 `biwiki`、`biwiki_test` 分开。当前本机已完成配置，可直接启动。

在其他开发环境，由该 PostgreSQL 实例的管理员创建上述专用角色与两个库，
将两个库的 owner 设为该角色，并在本地 `.env` 填入连接信息。
账号无需超级用户、创建数据库或创建角色权限；测试在专用测试库中创建随机 schema。
不要将旧项目数据库作为测试库，也不要在文档中保存密码。

## 启动与验证

```bash
uv run --locked bi-wiki
```

也可以激活现有虚拟环境后执行 `python -m bi_wiki`。这个包入口现在启动服务。

默认监听 http://127.0.0.1:8020；文档在 http://127.0.0.1:8020/docs。
知识目录与 .env 的默认位置基于项目根路径解析，不随启动目录改变。
数据库不可达、未建表且禁用了初始化时，服务会明确启动失败。

```bash
curl --fail http://127.0.0.1:8020/health
curl --fail -X POST http://127.0.0.1:8020/api/v1/runs \
  -H 'Content-Type: application/json' -d '{"workflow_type":"query"}'
curl --fail http://127.0.0.1:8020/api/v1/runs/替换为返回的UUID
```

POST /runs 只登记 queued 任务，不会执行、派发或自动生成成功状态。重启服务后仍可读取记录。
普通请求不能设置任务状态、时间、结果或错误。

预留能力会如实返回 HTTP 501，而不是假造答案或审批成功：

```bash
curl -X POST http://127.0.0.1:8020/api/v1/queries \
  -H 'Content-Type: application/json' -d '{"question":"什么是DAU？"}'
```

响应的 code 为 FEATURE_NOT_IMPLEMENTED。Ingest、Lint、Approve、Cancel 同样预留，详见 /docs。
健康检查实际访问 PostgreSQL 任务表；运行期不可用返回 503 / DATABASE_UNAVAILABLE。

## 配置

| 环境变量 | 默认 / 要求 |
|---|---|
| BI_WIKI_DATABASE_URL | 必填，PostgreSQL URL；作为敏感值处理 |
| BI_WIKI_TEST_DATABASE_URL | 测试时必填，独立的 *_test 库 |
| BI_WIKI_HOST | 127.0.0.1；当前只接受本机地址 |
| BI_WIKI_PORT | 8020 |
| BI_WIKI_LOG_LEVEL | INFO |
| BI_WIKI_KNOWLEDGE_ROOT | 项目根下 knowledge；启动不会写入它 |
| BI_WIKI_DATABASE_TIMEOUT_SECONDS | 5 |
| BI_WIKI_INITIALIZE_DATABASE | true；仅创建新表，不升级已有结构 |
| BI_WIKI_DATABASE_SCHEMA | public；测试使用随机 schema |

配置优先级：显式实例参数 > 环境变量 > 根目录 .env > 默认值。请求日志包含关联 ID、路由模板、
状态与耗时，不记录原始正文或数据库连接字符串。服务当前为本机开发使用，业务 API 已启用 MOA 认证。

## 测试

```bash
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build
```

测试先校验独立 PostgreSQL URL，再创建随机 test_<UUID> schema。测试不会清空运行库。
测试覆盖持久化、应用重启、状态并发、错误与占位接口；不执行真实模型调用。
可只运行不依赖数据库的配置测试：`uv run --locked pytest -q tests/test_config.py`。

架构和阶段边界见 [开发基线](docs/Agent_Service_Master_Specification.md)，实际结果见
[阶段 1 报告](docs/PHASE1_REPORT.md)。本项目参考了
[Gitee knowledge-base 的架构职责](https://gitee.com/cdkjframework/knowledge-base#架构)和现有 BI-WIKI；
实现独立，没有迁入向量模型、解析器或业务运行数据。

## 日志

参考旧 BI-WIKI 的统一入口、可选文件轮转和分步计时，保留本项目 JSON 格式。
应用及 Uvicorn 生命周期日志输出控制台；默认不创建日志文件。
设置 `BI_WIKI_LOG_FILE=var/log/bi_wiki.jsonl` 可同时输出 JSONL 文件，按 UTC 午夜轮转，
`BI_WIKI_LOG_BACKUP_COUNT=7` 保留 7 个历史文件。相对日志路径按启动工作目录解析，
也可填写绝对路径。文件轮转适用于当前单进程服务；多进程应使用控制台集中采集或独立文件。

每条日志包含时间、级别、logger 和代码位置。请求日志包含服务生成的 request_id、路由模板、
状态码和耗时；包括异常及流式响应结束路径。请求头中的任意关联 ID 不会被直接信任。
任务登记和状态转换仅在数据库事务提交后记录 run_id、workflow、stage、status，自动关联当前请求。
Run 数据库记录仍是任务状态依据，日志用于诊断。

```python
import logging
from bi_wiki.core.logging import log_context, timed_step

logger = logging.getLogger(__name__)
# 在 bi_wiki 包内使用模块 logger；阶段名与事件名用固定标识符。
with log_context(run_id="任务UUID", workflow="query"):
    with timed_step("retrieve"):
        logger.info("retrieval_started")
```

上下文支持嵌套并隔离并发任务。未来跨进程 Worker 需要从任务输入重新绑定 run_id，不能依赖
HTTP 上下文跨进程传播；独立异步任务也应显式管理自己的上下文生命周期。

异常输出类型和最多 32 个调用栈位置，不输出异常正文、源码行、局部变量或 SQL 参数。
第三方库采用相同 JSON 格式，但消息正文替换为 third_party_log，只保留 logger、代码位置和
异常栈等诊断元数据；SQLAlchemy/httpx/asyncpg 默认 WARNING，禁用重复的 Uvicorn 访问日志。
应用日志仅允许约定的附加字段，URL、Bearer 和常见凭据赋值作兜底替换。不要主动记录请求正文、
Prompt、凭据或原始 SQL：正则过滤无法识别所有任意敏感文本。

所有输出均在本机，不发送至外部日志平台；尚未接入 OpenTelemetry 或 LangSmith。

## 接口依赖

`api/deps.py` 集中定义 `get_database()`、`get_run_repository()` 及其 Annotated/Depends 类型别名。
路由通过 `db: DatabaseDep`、`repo: RunRepo` 声明依赖；lifespan 创建资源，app.state 保存实例。
测试可使用 `app.dependency_overrides` 替换依赖，结束后移除覆盖。业务服务和 Repository 使用普通
构造函数注入，不依赖 FastAPI 的 Depends。

## MOA 登录与前端

后端启动：`uv run --locked bi-wiki`，默认 127.0.0.1:8020。
前端在 `/Applications/materials/works/gits/bi_wiki_web` 执行 `npm ci`、`npm run dev`，访问
http://127.0.0.1:5174。Vite 将 /api 代理到新后端，不依赖旧 BI-WIKI 服务。
代码更新后请重启原后端进程，使认证生效。

MOA 配置见 .env.example；默认使用旧 BI-WIKI 的门户及项目 1564。新应用若分配独立项目 ID，
修改后端 BI_WIKI_MOA_PROJECT_ID 即可，前端从 /api/v1/auth/config 获取一致配置。
真实门户必须允许本机回调地址并保留 redirect 内的 moa_state 参数；若不允许，需要在 MOA
应用配置登记回调，不能通过取消 state 校验或关闭认证绕过。

接口约定：
- GET /api/v1/auth/config：公开的门户地址和项目 ID。
- POST /api/v1/auth/session：X-MOA-Token 请求头，校验原 token、刷新、再校验新 token；返回 token 和 user。
- GET /api/v1/auth/me：X-MOA-Token 请求头，返回服务端认证的 uid/name/nick。
- 原 Run/Workflow 接口均要求 X-MOA-Token；匿名请求返回 401，而不是原来的 201/501。
- GET /health 保持公开。上文无 token 的业务 curl 示例现在返回 401，需登录取得凭据后调用。

仅提供 MOA 模式，无本地绕过。客户端 UID/姓名不作为认证依据；认证网络失败返回 503。
前端将 token 存在 sessionStorage，退出清理本地状态并跳转 MOA logout，不建立自有持久会话。
当前 Run 是应用级共享记录，尚未实现按用户/项目隔离；前端仅登录壳，不开放任务或知识数据界面。
真实账号门户登录须人工完成；自动测试中的 MOA 成功响应为模拟，不能代表真实账号验收。

## Swagger 调试认证接口

先在前端登录。在已登录的前端标签页，打开浏览器开发者工具 Application → Session Storage →
当前前端 origin，复制 bi_wiki_web.moa.token 的值（仅用于本地调试，不要发送给别人）。
打开后端 /docs，点击 Authorize，在 MOA 中填写 token 原文，不加 Bearer 前缀，然后执行接口。
前端 sessionStorage 不会自动共享给后端 Swagger。缺少凭据返回 AUTH_TOKEN_MISSING，
无效/过期凭据返回 UNAUTHENTICATED。token 更新后需重新 Authorize；Swagger 不自动刷新凭据。

## 统一响应与接口编写

所有应用 JSON 接口，包括 `/health` 和 `/api/v1/auth/*`，采用同一结构：

```json
{"code":"OK","message":"操作成功","data":{},"request_id":"请求ID","details":[]}
```

成功的 `data` 为接口业务数据；失败的 `data` 为 null，`code` 为如 `RUN_NOT_FOUND` 的错误码，
`message` 为可展示信息，`details` 仅包含参数错误位置和类型。HTTP 仍使用 200/201/401/404/422/501 等。
任务 ID 位于 `data.run_id`。`request_id` 与响应头 `X-Request-ID` 一致。
Swagger `/docs` 和 OpenAPI 描述文件保持框架原格式。

新增接口使用 `ApiRouter`，它集中声明公共错误模型；成功返回使用 `ApiResponse[T]` 和 `ResponderDep`：

```python
@router.get("/example", response_model=ApiResponse[ExampleRead])
async def example(reply: ResponderDep) -> ApiResponse[ExampleRead]:
    return reply.ok(ExampleRead(...))
```

业务错误抛出 `ServiceError`，由全局处理器生成统一结构，无需逐个路由重复声明 404 等错误模型。
路由依然要配置认证依赖；`ApiRouter` 只统一响应声明，不会自动增加认证。
业务 curl 示例需要另加 `-H "X-MOA-Token: $MOA_TOKEN"`；缺少凭据先返回 401。
前端已同步使用统一请求客户端解包。更新后重启后端并刷新前端，避免新旧格式混用。

## Ontology Ingest 首版

已增加来源上传、候选定义与关系、计划审核、原子发布、知识与历史版本浏览，以及版本化提取配置。
前端访问 http://127.0.0.1:5174，登录后依次使用「来源资料 → 生成计划 → 审核 → 知识库」。
上传支持 UTF-8 Markdown/TXT，最多128 KiB和60000字符；原始字节保存在 var/raw，不覆盖。
每个MOA用户独立空间，本人审批自己的计划。还没有团队共享/审批角色管理。

模型配置（项目根 .env）：

```dotenv
BI_WIKI_LLM_BASE_URL=https://your-provider.example/v1
BI_WIKI_LLM_MODEL=your-model
BI_WIKI_LLM_API_KEY=replace-locally
```

地址后由服务追加 /chat/completions。协议要求 JSON object 输出；请求总超时由统一配置推导，
模型网络超时120秒。未配置会明确拒绝生成，上传与已有知识浏览仍可使用。不复制旧项目凭据。
修改环境后重启 `uv run --locked bi-wiki`；前端运行 `npm run dev`。
默认初始化新增6张 ontology_* 表，不修改既有Run表；无需新数据库容器。

本节覆盖前文 Ingest/Approve 均为501的历史说明。新的输入/输出、限制与验收详见
[Ingest v1](docs/INGEST_V1.md)。Query、独立Lint、通用Cancel仍为501。
业务API使用既有统一响应和X-MOA-Token。Ingest POST为同步生成，任务失败时读取 data.run.error；
HTTP200表示成功返回任务状态，不代表知识已经发布。


### 统一模型 Provider

`src/bi_wiki/llm/base.py` 定义 `ModelProvider.complete(messages, ...) -> str`，
`openai_compat.py` 实现 HTTP 协议、鉴权、超时、响应大小限制和错误分类，
`factory.py` 在应用启动时创建 Provider。支持 chat/completions HTTP Provider 和 CLI Provider，均返回完整文本。
连接配置统一使用 `BI_WIKI_LLM_BASE_URL`、`BI_WIKI_LLM_MODEL`、
`BI_WIKI_LLM_API_KEY`；修改后重启服务。不读取旧 BI-WIKI 凭据。

业务通过构造函数注入 Provider；Extractor 只负责提示词和 Ontology 输出校验：

```python
answer = await provider.complete(messages, temperature=0, max_tokens=12000, json_object=True)
```

通用调用可省略提取专用参数。新增业务复用 Provider 接口；若需独立模型，使用独立
ModelConfig 构造实例，在应用组合层注入，业务内部不读取连接配置。
401/403/429、超时、连接失败、响应格式错误分别分类为 MODEL_AUTH_FAILED、
MODEL_ACCESS_DENIED、MODEL_RATE_LIMITED、MODEL_TIMEOUT、MODEL_UNAVAILABLE、
MODEL_RESPONSE_INVALID；有效文本不符合 Ontology Schema 时为 MODEL_OUTPUT_INVALID。
不转发网关原始错误正文。Ingest 已创建的任务执行失败时，结果中的 Run.status 为 failed，
Run.error 保存对应错误码；调用方应检查任务状态，不能仅凭 HTTP 200 判断提取成功。


### 选择模型 Provider

HTTP 使用 `BI_WIKI_LLM_PROVIDER=openai`（默认），配置 `BI_WIKI_LLM_BASE_URL`、
`BI_WIKI_LLM_MODEL` 和可选 `BI_WIKI_LLM_API_KEY`。
CLI 使用以下配置（示例命令需在服务运行环境中安装并完成授权）：

```dotenv
BI_WIKI_LLM_PROVIDER=cli
BI_WIKI_LLM_MODEL=your-model
BI_WIKI_LLM_CLI_COMMAND=["aimana","chat","--model","{model}","--no-stream"]
BI_WIKI_LLM_TIMEOUT_SECONDS=300
```

CLI 不需要 BASE_URL / API_KEY；鉴权由命令自身负责。命令读取 stdin 提示词，stdout 必须
只输出模型回答，不包含进度、日志或外层 JSON 包装。命令参数不经过 Shell，`{model}` 替换为
配置模型名；服务端命令不能由请求传入。不同 CLI 的参数不同，按其实际协议配置。
CLI 的 temperature/max_tokens 不自动转换成命令参数，需在命令数组中显式设置；json_object
通过提示词要求，领域结构仍由 Extractor 校验。两种 Provider 都限制响应大小与调用时间。
CLI 同时消费 stdout/stderr，执行超时或取消会清理进程；POSIX 系统同时清理所在进程组。
原 `BI_WIKI_INGEST_MODEL_*` 配置不再读取，没有别名兼容。修改配置后重启服务。


### 超时设置

BI_WIKI_LLM_TIMEOUT_SECONDS 默认300秒（最大3600），INGEST_OVERHEAD_SECONDS 默认30秒、
INGEST_RECOVERY_GRACE_SECONDS 默认60秒，均需BI_WIKI_前缀。
Ingest执行期限=模型+overhead；中断恢复阈值=执行期限+grace；前端等待=执行期限+30秒。
HTTP模型调用同时受总时长与10秒连接超时限制。GET /api/v1/ingest-config 返回 timeouts，
每个新任务固定保存该策略，恢复按最后更新时间和保存的阈值判断。旧任务使用当前策略兜底。
GET /api/v1/ingest-requests/{key} 可只读查询本人原请求对应任务，无新建任务副作用。
目前POST /ingests仍同步等待；前端等待超时后查询原请求，若仍运行则按run_id轮询。
若部署反向代理，其响应等待期限需大于执行期限。异步提交202+run_id尚未实现。

### S3 RawStore

Raw 存储可通过 `BI_WIKI_RAW_BACKEND=local|s3` 切换，默认本地。本地 `RawStore` 与
`S3RawStore` 提供同一 `put(owner, bytes)` / `read(owner, sha256)` / `close()` 接口，
IngestService 继续在线程池中调用；lifespan 通过 `create_raw_store` 装配并释放客户端。

```dotenv
BI_WIKI_RAW_BACKEND=s3
BI_WIKI_S3_BUCKET=your-existing-bucket
BI_WIKI_S3_PREFIX=bi-wiki/raw
BI_WIKI_S3_REGION=us-east-1
# 仅 S3 兼容服务需要自定义 endpoint / addressing style
# BI_WIKI_S3_ENDPOINT_URL=http://127.0.0.1:9000
# BI_WIKI_S3_ADDRESSING_STYLE=path
```

凭据可使用 boto3 标准凭据链或显式 S3_ACCESS_KEY/S3_SECRET_KEY（均加 BI_WIKI_ 前缀），
临时凭据可设置 S3_SESSION_TOKEN。密钥仅在环境配置，不能放前端。代码不复制老项目凭据。
对象键为 `<prefix>/<sha256(owner)>/<sha256(content)>`，原字节保存；数据库仍登记来源元数据。
桶需要预先存在，程序不自动建桶；运行身份需要该前缀内 GetObject/PutObject 权限。
不开放公网对象或向浏览器返回预签名链接，读取继续经过 MOA 与来源归属校验。

写入使用 `IfNoneMatch="*"`，已有对象返回412后读取并核验内容，不覆盖。
不支持条件写入的兼容服务会明确失败，不回退为可覆盖上传。409冲突可重新提交请求，
不伪报成功。读取限制128KiB并校验SHA-256，网络读取体始终关闭。
S3原始文件成功但数据库事务失败时不删除原始文件；重试按内容哈希核验后登记。

**切换不等于迁移。** 当前存储选择是部署级配置，来源表未记录逐条存储位置；已有来源必须先
复制到新桶的同一对象键并核验，才能切换，否则旧来源读取失败。此版本不自动迁移或双读。
`/health` 仍检查数据库，不保证 S3 权限可用；存储权限和端点在真实读写时验证。
S3单测使用 botocore Stubber，接口测试结合真实隔离PostgreSQL；未执行真实S3/MinIO端到端验收。
