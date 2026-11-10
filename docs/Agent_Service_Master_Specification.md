# BI Wiki 服务开发基线

文档编号：BIWIKI-ADS-BASELINE-001  
版本：V1.2  
日期：2026-11-10  
当前实施范围：阶段 1 服务基础，以及用户于 2026-11-10 授权的 MOA 认证和独立前端登录壳。

## 1. 目标与当前边界

产品长期围绕 Ontology 的定义、从材料生成定义，以及 NL2Ontology 在知识理解、数据查询和
开发任务中的使用。本阶段建立能启动、能配置、能检查数据库健康、能持久保存任务的后端。
本阶段不声称已经建立业务 Ontology，也不执行模型、知识检索或知识编译。

这是 `/Applications/materials/works/gits/bi_wiki` 的独立新项目。现有
`/Users/huangsien/PycharmProjects/BI-WIKI` 只作设计参考，不复制其凭据、运行数据或整套业务模块。

## 2. 参考资料与取舍

- 蓝尘《LLM Wiki Agent 服务的基本要求》与《怎么搭建 LLM Wiki Agent 服务》：依据用户提供的正文。
  采用知识资产与服务代码分离、显式工作流、受限工具、真实状态和分阶段验收思想。
- [Gitee knowledge-base 架构](https://gitee.com/cdkjframework/knowledge-base#架构)：核对 README 的
  HTTP API、store、knowledge base、解析器 facade 分层。这里只参考职责拆分；未移植代码或验证其实现。
- 现有 BI-WIKI：参考应用工厂、lifespan、Settings、PostgreSQL 会话和独立测试库防误连模式。
- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) 和
  [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)。

文章中的冻结文档编号、SQLite、Agents SDK、Celery/Redis 和每阶段审批并不是本项目自动继承的要求。
本项目沿用已经确认的 PostgreSQL 偏好；当前不引入模型 SDK、向量数据库和后台队列；前端范围见第 11 节。

## 3. 模块化单体

| 层 | 当前位置 | 职责 |
|---|---|---|
| API | src/bi_wiki/api | 参数校验、HTTP 状态与响应；不执行模型或文件操作 |
| 任务契约 | src/bi_wiki/models | 工作流类型、状态、请求与响应 |
| 持久化 | src/bi_wiki/repositories、db | 事务存取、并发状态转换、PostgreSQL 约束 |
| 公共控制 | src/bi_wiki/core | 配置、统一错误、结构化日志 |
| 生命周期 | src/bi_wiki/main.py | 初始化与清理实例资源 |
| 知识资产 | knowledge | 后续来源、Wiki、Schema 与模板；阶段 1 不读写资产 |
| 运行产物 | var | 后续报告和 staging，默认不入 Git；当前不创建虚假产物 |

后续 Agent Runtime 负责模型决策与工具调用；Workflow 负责预定义阶段及状态，Tools 负责受限操作。
Agent 是否存在自主循环必须由运行行为判断，不能依据目录名或是否调用了 LLM 判断。
这些未来模块当前不创建空实现或假成功接口。

## 4. 技术与配置

Python 3.12+、FastAPI、Pydantic Settings、SQLAlchemy 2.0 async、asyncpg、PostgreSQL。
项目根 pyproject.toml 管理依赖，uv.lock 固定解析结果；复用目标目录已有 .venv。

环境变量统一使用 `BI_WIKI_` 前缀；配置优先级为显式实例参数、环境变量、根目录 .env、代码默认值。
数据库 URL 为必填 SecretStr，无源码内默认密码；接受 postgresql / postgresql+asyncpg，并统一使用 asyncpg。
知识目录路径仅解析，不因加载设置或启动应用创建、扫描或修改知识文件。
启动命令默认绑定 127.0.0.1:8020；本阶段配置只允许本机监听。

## 5. 阶段 1 API

| 接口 | 行为 |
|---|---|
| GET /health | 查询真实 PostgreSQL 任务表，健康返回 200；不可用返回 503 |
| POST /api/v1/runs | 仅登记 queued / registered 任务，返回 201 和 Location，不派发、不执行 |
| GET /api/v1/runs/{run_id} | 读取持久化记录；不存在 404，非法 UUID 422 |
| POST /api/v1/ingests | 校验 source_ref，返回 501 FEATURE_NOT_IMPLEMENTED |
| POST /api/v1/queries | 校验 question / scope，返回同样的 501 |
| POST /api/v1/lints | 校验 scope，返回同样的 501 |
| POST /api/v1/runs/{run_id}/approve | 校验 plan_version，返回 501，不批准、不改状态 |
| POST /api/v1/runs/{run_id}/cancel | 校验 reason，返回 501，不取消、不改状态 |

任务登记请求只接受 workflow_type（ingest / query / lint），禁止提交 status、时间、结果或错误。
没有通用 HTTP 状态修改接口。预留工作流返回 501 时不创建假运行记录。
登记接口的 queued 只表示已记录待执行意图；阶段 1 没有 Dispatcher，因此不会自动推进。

所有应用 JSON 接口（含 health、auth、runs、reserved）统一为
`{"code":"OK","message":"操作成功","data":{},"request_id":"...","details":[]}`。
成功 data 为接口声明的类型；错误 code 为错误码、data 为 null。保留真实 HTTP 状态码。
ApiRouter 集中声明错误模型，ApiResponse[T] 声明成功模型，ResponderDep 构造成功响应；
异常处理器构造相同结构。框架 /docs、/openapi.json 不包裹。
参数错误额外返回字段位置和错误类型，不回显原始输入。响应携带 X-Request-ID。
数据库异常和内部异常的响应与应用日志不包含 DSN、SQL 参数或异常原文。
OpenAPI 可在 /docs 查看当前请求和响应模型。

## 6. Run 数据与转换

wiki_run 字段：run_id（UUID 主键）、workflow_type、status、stage、version、created_at、updated_at、
started_at、completed_at、result_ref、error。时间存为 TIMESTAMPTZ，使用 UTC；error 为可空 JSONB。

内部 Repository 允许的状态转换：

- queued → running / cancelled。
- running → succeeded / failed / cancelled；只有 ingest 可以进入 awaiting_approval。
- awaiting_approval → running / cancelled，仅为未来工作流提供状态基础，不等于当前已实现审批。
- succeeded / failed / cancelled 为终态，阶段 1 不允许重新打开。

每次转换比较旧 version 与 status，在同一 UPDATE 中递增 version；并发竞争只允许一次成功。
失败必须有结构化 error；其它状态不携带 error。终态有 completed_at；执行与失败状态有 started_at。
首次 started_at 在审批等待和恢复运行之间保持不变。状态、工作流和时间字段有数据库约束。
不能把内部 Repository 的状态机测试当作 Ingest / Query / Lint 已经执行。

## 7. 数据库初始化与测试隔离

启动默认 create_all 创建本服务尚不存在的表，并检查任务表；失败则启动失败并清理连接池。
设置 BI_WIKI_INITIALIZE_DATABASE=false 可跳过建表，但仍必须通过存储检查。
create_all 不升级已有表。后续表结构改变需要独立迁移方案，不能假称初始化已经迁移旧库。

测试必须显式提供 BI_WIKI_TEST_DATABASE_URL。要求 PostgreSQL、库名以 _test 结尾，且库名与
运行库不同。任何测试 DDL 之前完成校验；不自动派生或复用旧 BI-WIKI 的数据库。
每个数据库测试创建随机 test_<UUID> schema，结束只删除自己的 schema，不清空整个数据库。
重启测试必须关闭应用和连接池后重建，再读取先前提交的同一条记录。

## 8. 后续三个 Workflow 的职责草案

Query：问题与范围 → 定位定义/知识页面 → 按需读取来源 → 判断覆盖与歧义 → 回答或语义计划与证据。
只读知识资产，可保存运行记录；不能将保存 Run 与修改知识库混为一谈。

Lint：先确定性格式、引用和约束检查，再语义审查。模型未运行时明确 NOT_RUN，语义结果为待核实建议。
默认只报告；正式修复由后续独立变更契约控制。

Ingest：校验来源 → 登记原始字节与哈希 → 提取有证据的候选定义/关系 → 比较已有知识 →
生成变更计划 → 按最终确定的发布政策审查 → staging 校验 → 受控提交 → 保存结果和恢复记录。
Raw 来源不可被生成过程原地改写。来源注册成功不等于知识编译成功。

后续要求保留来源位置、版本/内容摘要、不确定点和冲突。页面 Schema 不自动等于 Ontology 元模型。
本阶段尚未确定逐 Run 人工审批或自动发布策略；approve 只是预留 API。

## 9. 阶段路线

| 阶段 | 目标 | 门槛 |
|---|---|---|
| 1（当前） | 服务、配置、健康、任务持久化与测试 | 真正启动与数据库测试、明确 501、知识资产不被修改 |
| 2 | 受控 Ingest 与知识变更 | 来源去重、绑定版本的计划、staging 校验、幂等与中断恢复 | 
| 3 | 只读 Query 与只报告 Lint | 来源可追踪、缺口/歧义明确、确定性与语义检查分开 |
| 4 | 可靠后台运行与部署 | 持久派发、有限重试、跨进程状态一致性、访问控制和恢复演练 |

后续阶段的队列、Runtime、元模型和发布政策另行确认；阶段 1 不提前选型或实施。

## 10. 阶段 1 验收与交付

必须实际验证：配置优先级与非法值、PostgreSQL Run 存取、未知 ID、非法请求、合法/非法状态转换、
并发版本冲突、应用/连接重启后持久化、501 无副作用、数据库故障不泄密以及知识文件未变。
执行 pytest、Ruff 和一次真实 HTTP 启动/重启探针；记录结果，不用 Mock 数据代替持久化证据。
数据库故障响应测试可使用故障注入，须明确其性质。

本阶段报告写入 docs/PHASE1_REPORT.md，区分已实现、已验证、未验证和后续范围；完成后停在阶段 1。
不自动启动阶段 2，不 push、部署、迁移旧项目或提交已有用户改动。


## 11. V1.1 用户授权扩展：MOA 与前端登录壳

本节覆盖前文关于暂不引入前端或认证的阶段限制；其余知识工作流边界不变。
新前端目录 /Applications/materials/works/gits/bi_wiki_web，React + TypeScript + Vite + Ant Design。
只提供 MOA 登录、退出和空知识工作台，参考旧 BI-WIKI 的顶栏、侧栏和内容区。
后端 /health 与 /api/v1/auth/config 公开；所有 Run 和预留工作流接口通过 Depends 校验 MOA。
/api/v1/auth/session 刷新凭据并返回服务端身份，/api/v1/auth/me 获取当前身份。
后端使用 /api/getinfo 校验 token 和 project，身份取服务端 uid/name/nick，不接受客户端身份提示。
认证失败返回 401、项目不匹配返回 403、上游异常返回 503，禁止失败时免登录继续。
前端统一从后端读取门户地址及项目 ID，以 sessionStorage 保存当前标签页凭据；回调绑定随机 state，
在任何认证请求之前清理 URL 参数。不增加跨域 CORS 放行，开发用 Vite 代理，部署需同源反向代理。
当前是认证门禁，Run 仍是应用级共享记录；尚无用户/项目级资源隔离，前端不展示任务或业务数据。

## 12. V1.2 用户授权扩展：统一 API 响应

2026-11-10 用户要求统一所有接口。采用上述统一结构，前端 apiRequest 负责解包和错误处理。
这是响应格式变更，前后端须配套更新；不增加业务能力、不改变 MOA 门禁及任务状态语义。
