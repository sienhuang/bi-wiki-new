# 阶段 1 交付报告

日期：2026-11-10。状态：PASS（服务基础与任务持久化）。

## 已实现

- 独立 FastAPI 应用工厂、lifespan 与启动命令；实例关闭后释放数据库连接池。
- BI_WIKI_ 环境配置、根目录 .env、连接字符串敏感值处理和本机监听默认值。
- 真实访问 PostgreSQL 任务表的 /health；启动失败和运行期不可用分别明确报错。
- POST /api/v1/runs 登记 queued 任务，GET /api/v1/runs/{run_id} 读取持久化记录。
- Run UUID、工作流、状态、阶段、版本、UTC 时间、结果引用与结构化错误。
- 内部合法状态转换、终态保护、版本并发比较与 PostgreSQL 字段约束。
- 统一错误响应、关联请求 ID、结构化应用日志和实际一致的 OpenAPI 响应契约。
- Ingest / Query / Lint / Approve / Cancel 输入模型与 HTTP 501 占位，不创建虚假运行结果。
- 知识与代码目录分离、开发基线、项目记忆、安装启动和测试说明。

## 实际验证

| 验证 | 实际结果 |
|---|---|
| pytest -q --tb=short | 33 passed；持久化测试使用 PostgreSQL 16 |
| ruff check . | All checks passed |
| ruff format --check . | 全部 Python 文件格式检查通过 |
| uv build --offline | sdist 和 wheel 构建成功 |
| 真实 HTTP 进程探针 | /health=200，登记=201，预留查询=501；关闭进程后启动新进程，同一 Run 内容保持一致 |
| 构建产物内容检查 | 不包含本地 .env、虚拟环境和缓存文件 |

测试使用显式配置的独立 bi_wiki_test 数据库，每个用例只操作自己的随机 schema；真实 HTTP 探针也使用
独立 schema，结束后关闭两个进程并删除该 schema。没有清空运行库或旧项目数据库。
健康错误响应测试使用故障注入；缺失表的启动失败和持久化、并发、重启测试实际连接 PostgreSQL。
语义工作流和模型调用没有运行，也没有被报告为通过。

初次在受限沙箱运行时，本机 TCP 被拒绝：13 个纯配置测试通过，数据库用例在连接阶段失败。
随后获得本机数据库访问能力并完整重跑，33 项通过；没有通过改用 SQLite 或跳过数据库测试绕过。
Ruff 首轮发现格式和导入顺序问题，格式化后检查通过。

## 本地数据库

首次验收曾使用独立 PostgreSQL 16 容器。用户随后明确要求复用现有 `metadata-kb-postgres`，
现已切换到该容器的 PostgreSQL 14（127.0.0.1:5432），使用新项目专用非超级用户角色 bi_wiki、
运行库 bi_wiki 和测试库 bi_wiki_test。已有 biwiki、biwiki_test 及其他数据库未修改。
原独立容器的运行库无应用表或记录，无需迁移；原容器停止，容器与数据卷保留。
本地 .env 已切换且忽略提交；.env.example 仅包含占位凭据。

切换后重新执行 `pytest -q -p no:cacheprovider`：33 passed（真实 PostgreSQL 14）。

## 文件范围

- pyproject.toml、uv.lock、.gitignore、.env.example、README.md、AGENTS.md。
- src/bi_wiki：生命周期、CLI、core、models、db、repositories、api。
- tests：配置、API、持久化与并发测试。
- docs：开发基线、项目记忆和本报告。
- knowledge：五个空目录的 .gitkeep；没有生成正式知识内容或业务 Ontology。

开工时目标目录只有 .git 与 .venv；写入前再次检查发现新增加了最小 Python 骨架。
因此整合时沿用现有项目名称 bi-wiki 和 src/bi_wiki 包布局，将 python -m bi_wiki 入口升级为服务启动，
并重新验证测试和 HTTP 重启。已有忽略规则保留，.git 与 .venv 继续复用。
旧 BI-WIKI 的业务代码、数据和用户未提交修改不在交付范围。

## 限制与后续

- 当前没有 Dispatcher / Worker；登记的 queued 任务不会被自动执行。
- Query / Lint / Ingest、真实模型、审批/取消执行均未实现。
- 首次交付未含认证；本轮已按用户授权补充 MOA 门禁，详见后续补充记录。仍未发布公共服务。
- create_all 只创建新表，不升级已有数据库结构；后续变更需显式迁移。
- 尚未测试队列、跨 Pod 部署或生产备份恢复，这些不属于阶段 1。
- Mana CodeWiki 检索尝试因登录续期失败未返回内容；已有项目约束与实现参考已通过本地原文核对。

服务基础具备进入下一阶段的条件；本次停在阶段 1，下一阶段由用户指定。


## 补充调研：OpenWiki 与观测接入（2026-11-10，未实施）

已只读核验 OpenWiki README 和 commit `261b9ffa57493f9768d6e565d444194c7ee5cadc`
的 telemetry／LangSmith connector。匿名产品统计、应用调用链观测、Wiki 消费运行记录
是独立能力。现成 Wiki 增强路径为应用 → LangSmith → OpenWiki 原生 CLI code 模式；
宿主驱动的生成流程当前不消费连接器上下文。

对本项目，现有 FastAPI、SQLAlchemy async 和结构化请求日志可承接后续观测；基础
HTTP/数据库链路和真实工作流步骤应分步评估，并维持敏感内容不进入日志的约束。
未安装 SDK、配置凭据、连接观测后端或发送测试 trace，也未重新运行阶段 1 测试。
上述为参考评估，不构成后续阶段的实施或平台选型。

参考：[OpenWiki LangSmith connector](https://github.com/langchain-ai/openwiki#langsmith-connector-code-mode)、
[LangSmith Python 埋点](https://docs.langchain.com/langsmith/annotate-code)、
[OpenTelemetry FastAPI](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html)。

## 日志基础能力增强（2026-11-10）

用户授权参考旧 BI-WIKI 补充日志。已参考 app/infra/logger/logging.py 和 timing.py，
保留新项目 JSON，统一应用及 Uvicorn 日志入口；ContextVar 绑定 request_id/run_id/workflow/stage，
纯 ASGI 中间件在成功、异常、流式结束路径记录请求完成。任务日志在事务提交后输出。
异常仅记录类型与调用栈位置，第三方消息正文不输出；默认控制台，可选 UTC 日轮转文件，
保留数可配置，单进程适用。提供 timed_step；未引入观测 SDK 或外部上报。
真实 metadata-kb-postgres 上执行 pytest -q -p no:cacheprovider：39 passed；Ruff 检查通过。
新增覆盖上下文并发隔离、异常脱敏、重复初始化、文件轮转、请求失败及 Run 关联。


## Telemetry 范围澄清（2026-11-10）

用户明确只考虑 telemetry，不接入 LangSmith。当前仅评估参考 OpenWiki 的匿名事件统计，
具体上报后端和事件字段尚未选定；未新增 SDK、发送事件或改变阶段 1 的实施边界。
本次仅补充范围说明，未修改运行代码或重新执行运行测试。

## 接口依赖注入（2026-11-10）

按用户决定，HTTP 接口统一通过 api/deps.py 的 Depends 获取 Database 和 RunRepository。
lifespan 继续负责创建与释放，app.state 保存共享实例；内部类仍通过构造函数接收依赖。
健康检查与 Run 路由不直接读取 app.state。测试验证数据库依赖替换后 503 与恢复，以及
两个 Run 路由的 Repository 替换；完整 PostgreSQL 回归 40 passed，Ruff 通过。

## 用户授权扩展：MOA（2026-11-10）

新增 services/auth.py、api/auth.py；更新 Settings、lifespan、依赖及业务路由认证门禁。
httpx 提升为运行依赖。GET auth/config 公开，POST auth/session 校验并刷新，GET auth/me 返回身份。
身份来源为服务端 getinfo，项目不符403，无效token401，上游故障503。前端位于独立 bi_wiki_web。
本轮 `pytest -q -p no:cacheprovider`：53 passed（PostgreSQL 持久化 + 模拟 MOA 协议）；Ruff通过。
真实独立CLI进程：health200、config200、匿名me401、真实MOA拒绝的测试token经后端返回401。
直接探测真实 getinfo/refresh 均HTTP200且业务code104；测试token未出现在服务日志。
真实账号成功登录未执行。新前端构建通过；浏览器验收结果记录在前端项目文档中。

## 验证结果（2026-11-10）

- npm run build：TypeScript 检查与 Vite 生产构建通过。
- npm test：8 项 Playwright Chromium 测试通过；使用模拟门户与认证 API，不代表真实账号成功登录。
- 覆盖登录 URL/project/state、回调参数清理、服务端身份展示、退出清理、过期、错误项目、网络重试、
  后端不可用与窄屏无横向溢出。已检查登录后桌面截图。
- 真实 Vite → 新后端代理探针：页面200、auth/config200、匿名auth/me401；临时进程已关闭。
- 后端53项测试和Ruff通过；真实MOA负向请求被正确拒绝，测试token未进入日志。
- 未执行真实账号成功登录；需人工确认MOA应用1564允许前端回调并保留moa_state。

2026-11-10 补齐 Swagger 的 MOA APIKeyHeader 安全定义，Authorize 统一注入 X-MOA-Token。
缺失 token 返回 AUTH_TOKEN_MISSING，与过期/无效的 UNAUTHENTICATED 区分；仍需真实MOA校验。
前端 sessionStorage 不自动共享到 Swagger，调试时需显式授权；补充 OpenAPI 与缺失凭据回归。

## 统一 API 响应（2026-11-10）

用户授权统一接口结构，基线 V1.2。修改 models/responses.py、api/responses.py（新增）、
api/routes.py、api/auth.py、main.py 及相关测试。成功和错误均包含 code/message/data/request_id/details；
保留 HTTP 状态、MOA 安全声明、Location/Allow/Cache-Control 等响应头。
前端新增 api/client.ts 并同步认证调用和模拟 API。

- `.venv/bin/ruff format src tests`、`.venv/bin/ruff check --fix src tests`：通过。
- `.venv/bin/pytest -q -p no:cacheprovider`：62 passed；真实 PostgreSQL，MOA 使用模拟协议。
- `npm run build`：通过。
- `TEST_PORT=5187 npm test`：8 passed，模拟登录，不代表真实账号验证。
- 新增统一结构检查覆盖健康、认证、任务登记/查询、401/404/405/422/500/501、请求 ID、敏感信息保护。
- 未部署、未调用真实账号登录；前后端须配套更新。未进入知识工作流阶段。

## 后续用户授权的 Ingest v1

阶段1历史结果保持；2026-11-10用户授权首版Ontology Ingest及前端，当前报告见INGEST_V1.md。
84项后端测试、9项浏览器模拟测试、前端构建与真实前后端/数据库联调通过；真实模型尚未配置验收。
