# bi_wiki 项目记忆

最近更新：2026-11-10。

- 用户要求在 /Applications/materials/works/gits/bi_wiki 创建独立新项目，参考两篇 LLM Wiki Agent
  文章、Gitee cdkjframework/knowledge-base 架构，以及旧 BI-WIKI，先实现服务基础阶段。
- 产品长期主线为 Ontology 的定义、自动产生与使用，以及 NL2Ontology；当前阶段不提前实现业务本体。
- 当前交付边界：FastAPI、集中配置、真实数据库健康检查、Run 登记/读取与持久化、错误、日志和测试。
- PostgreSQL 用于运行和测试。测试要求显式独立 *_test 库，按用例随机 schema 隔离。
- 保留已有 .git 与 .venv；不迁移旧 BI-WIKI 的运行数据、凭据或未提交业务代码。
- 开工期间目标目录新增了最小 Python 骨架，实施沿用其 bi-wiki 项目名称与 src/bi_wiki 包布局；
  python -m bi_wiki 入口用于启动服务，没有建立第二套 Python 包。
- Ingest、Query、Lint、Approve、Cancel 当前为明确返回 501 的契约，不执行模型或修改知识资产。
- POST /api/v1/runs 只登记 queued 记录，当前没有 Worker/Dispatcher。状态转换仅供内部后续运行时使用。
- 当前只支持本机开发监听。模型 Runtime、Ontology 元模型、队列、发布政策和部署仍留待后续阶段。
- 开发基线：BIWIKI-ADS-BASELINE-001 V1.2；本阶段实际验证结果以 docs/PHASE1_REPORT.md 为准。


## OpenWiki 与 telemetry 调研（2026-11-10，仅评估）

- 已只读核验 langchain-ai/openwiki 的 README 及 commit
  `261b9ffa57493f9768d6e565d444194c7ee5cadc` 的 telemetry 和 LangSmith connector 源码。
- README 的 Telemetry 是 PostHog 匿名使用统计；OpenWiki 自身的 LangSmith tracing、
  读取外部应用 trace 的 LangSmith connector 与之分别承担职责。
- 现成运行记录增强路径为 Python 应用 → LangSmith → OpenWiki 原生 CLI code 模式。
  普通 Python 函数可通过 LangSmith SDK 手动埋点；无需以 LangChain 编排应用。
  当前宿主驱动的代码 Wiki 生成不支持 connector 上下文。连接器只允许配置的官方
  US/EU/APAC API 主机，抽样读取结构、时序、token 和错误，不请求 inputs/outputs；
  该限制属于读取端，不能替代应用写入端的敏感内容控制。
- 当前服务已有 request_id 和结构化日志，pyproject 尚无 OTel/LangSmith 依赖。
  后续可先评估 HTTP/数据库自动观测，再为真实工作流添加业务步骤与 Run 关联；
  仅通用 OTel 采集不等于 OpenWiki 已能直接读取对应后端。
- 本轮没有选择观测平台、安装 SDK、启用上报或实施后续工作流；阶段 1 边界保持。

## 本地数据库复用（2026-11-10）

用户明确要求复用现有 metadata-kb-postgres，不新建 PostgreSQL 镜像或容器。
已切换到 127.0.0.1:5432 的 PostgreSQL 14，专用非超级用户角色 bi_wiki，独立库
bi_wiki / bi_wiki_test；与旧项目 biwiki / biwiki_test 分离。33 项测试重跑通过。
原 bi-wiki-stage1-postgres 停止并保留数据卷，其运行库无应用表或记录，无需迁移。

## 日志基础能力增强（2026-11-10）

用户授权参考旧 BI-WIKI 补充日志。已参考 app/infra/logger/logging.py 和 timing.py，
保留新项目 JSON，统一应用及 Uvicorn 日志入口；ContextVar 绑定 request_id/run_id/workflow/stage，
纯 ASGI 中间件在成功、异常、流式结束路径记录请求完成。任务日志在事务提交后输出。
异常仅记录类型与调用栈位置，第三方消息正文不输出；默认控制台，可选 UTC 日轮转文件，
保留数可配置，单进程适用。提供 timed_step；未引入观测 SDK 或外部上报。
真实 metadata-kb-postgres 上执行 pytest -q -p no:cacheprovider：39 passed；Ruff 检查通过。
新增覆盖上下文并发隔离、异常脱敏、重复初始化、文件轮转、请求失败及 Run 关联。


## Telemetry 范围澄清（2026-11-10）

用户明确不接入 LangSmith，本轮仅评估 telemetry。参考对象是 OpenWiki 的匿名事件统计，
LangSmith connector 和 LLM tracing 均不属于当前接入目标；此前相关调研仅保留作背景。
具体事件字段、上报后端和采样策略尚未决定。本轮未新增 SDK，也未开启外部上报。

## 接口依赖注入（2026-11-10）

按用户决定，HTTP 接口统一通过 api/deps.py 的 Depends 获取 Database 和 RunRepository。
lifespan 继续负责创建与释放，app.state 保存共享实例；内部类仍通过构造函数接收依赖。
健康检查与 Run 路由不直接读取 app.state。测试验证数据库依赖替换后 503 与恢复，以及
两个 Run 路由的 Repository 替换；完整 PostgreSQL 回归 40 passed，Ruff 通过。

## MOA 认证与独立前端（2026-11-10）

用户明确授权在现有基础上增加 MOA 认证与独立 bi_wiki_web 前端，基线更新 V1.1。
后端保留 Depends 依赖边界；/health 和 auth/config 公开，业务 API 要求 X-MOA-Token。
参考旧 BI-WIKI 的门户跳转与刷新流程，身份改为服务端 auth-api.moa.moonton.net/api/getinfo
返回的 uid/name/nick，并校验 project；不沿用旧项目采信客户端身份 hints 的做法。
本地 agent-gateway 的 MoaUtils/MoaConfig/MoaTokenInfo 提供 getinfo 协议依据；Mana 登录续期失败。
默认项目 ID 1564 与旧 BI-WIKI 一致，可由后端配置调整。没有 dev 绕过或真实凭据迁移。
前端目录 /Applications/materials/works/gits/bi_wiki_web，端口5174代理后端8020；React/Ant Design，
蓝绿顶栏、侧栏、空工作台。回调清理 URL 并校验 state，sessionStorage 保存 token。
后端53项测试及Ruff通过；真实MOA负向探针返回code104，真实后端将其转为401，日志不含token。
真实账号成功登录、门户回调白名单与state保留尚待人工验证，不能将模拟成功测试视为真实验收。
当前Run为应用级共享记录，仅认证，无用户/项目资源归属隔离；前端不开放任务/知识业务数据。

前端8项浏览器测试、生产构建、真实Vite代理至新后端的匿名门禁探针均通过；MOA成功身份响应为模拟。

2026-11-10 补齐 Swagger 的 MOA APIKeyHeader 安全定义，Authorize 统一注入 X-MOA-Token。
缺失 token 返回 AUTH_TOKEN_MISSING，与过期/无效的 UNAUTHENTICATED 区分；仍需真实MOA校验。
前端 sessionStorage 不自动共享到 Swagger，调试时需显式授权；补充 OpenAPI 与缺失凭据回归。

2026-11-10 按用户要求统一全部应用 JSON 响应为 code/message/data/request_id/details，保留 HTTP 状态。
ApiRouter 集中错误模型，ApiResponse[T] 与 ResponderDep 构造成功响应，异常处理器处理失败。
前端 apiRequest 统一解包，MOA 门禁保留；docs/OpenAPI 不包裹。基线 V1.2。
62 项后端测试、Ruff、前端构建及 8 项模拟浏览器测试通过。需前后端配套更新，真实账号登录尚未验证。
