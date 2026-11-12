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

## Ontology Ingest 首版（2026-11-10）

用户确认前后端Ontology设计并要求开始首版，基线升级V1.3。已实现个人MOA空间内的MD/TXT来源、
原始字节与哈希去重、固定document-v1提取、ontology-v1候选定义/关系、原文证据校验、不可变计划、
本人批准/拒绝、PostgreSQL事务发布、知识和revision浏览。正式知识以数据库为依据，Markdown为
同事务派生展示文本；不创建第二套文件事实存储。Raw在var/raw独立保存。
配置页面可发布提取类型、数量和业务说明新版本，每Run固定配置快照；没有任意Schema/工具编辑。
生产代码未提供认证绕过。模型通过环境配置的chat/completions兼容服务调用；无配置时明确503。
当前固定提取步骤，不宣称自主Agent循环；未实现Query、独立Lint、通用Cancel、队列或多人审批。
验证：84项后端测试、Ruff、前端构建、9项浏览器模拟测试通过；真实浏览器→代理→API→PostgreSQL
隔离联调通过（身份/模型为测试替身），临时进程与数据清理完成。真实模型与真实账号成功登录未验收。
工作台chunk约619KB，已按需加载但仍有体积警告。启动/边界/完整报告见docs/INGEST_V1.md。


## 统一模型 Provider（2026-11-11）

用户授权抽出统一 Provider 层，重点是业务与模型连接分离，并非改为 CLI。
新增 llm 的 Protocol、配置工厂、OpenAICompatibleProvider；Extractor 构造注入 Provider，
只保留提示词与 Ontology 结构校验。lifespan 创建共享无连接状态 Provider，各次请求关闭 HTTP 客户端。
现有 INGEST_MODEL_* 环境配置继续有效，无凭据迁移、数据库/API结构变更或新增依赖。
HTTP失败分类且不回显上游正文，模型名称从Provider写入任务快照。
测试配置显式清空模型凭据，避免读取本地配置后意外请求真实网关。
验证：103项pytest通过（含独立PostgreSQL及MockTransport），Ruff通过。
真实模型成功调用尚未验收，先前预算池403不能由抽象层重构解决。


## 通用配置与 CLI Provider（2026-11-11）

用户明确不保留 INGEST_MODEL_* 兼容，已直接改为 BI_WIKI_LLM_PROVIDER/MODEL/BASE_URL/API_KEY，
增加 LLM_CLI_COMMAND（JSON参数数组）和 LLM_TIMEOUT_SECONDS。用户本地.env仅迁移字段名，
保留原配置值，不自动切换当前HTTP Provider。旧变量无别名、不再读取；本节覆盖上节兼容决定。
工厂支持 openai/cli；CLI通过stdin传提示词、stdout取纯文本，参数中{model}替换模型名。
CLI不通用映射temperature/max_tokens，需要具体命令自行配置；JSON仍须领域校验。
命令无Shell、stderr并发消费且不回显，stdout/stderr各限1MB；超时/取消清理进程及POSIX进程组。
全量115项pytest通过，含真实PostgreSQL和本地测试子进程；未执行真实CLI模型端到端调用。


2026-11-11 统一超时：模型300秒、执行330秒、客户端360秒、恢复390秒；配置由模型时间、
执行预留30秒、恢复宽限60秒推导。新任务保存策略快照，恢复依据最后更新时间，HTTP实现总时长限制。
前端获取策略并在等待超时后按原请求键只读查找，再按run_id轮询。117后端测试、10浏览器测试、
前端构建及Ruff通过。真实长文成功提取未验证。用户随后提出应直接轮询；当前POST仍同步，
异步立即返回202+run_id需要后续改造任务执行方式，尚未实现。


## 2026-11-11 真实模型链路验收

用户要求优先验证全流程，暂不优化模型耗时、不引入后台任务。
本地用户将模型等待设为3000秒、处理预留300秒、恢复宽限600秒；保留其值，
放宽配置允许的模型等待上限到3600秒。对应执行3300秒、前端3330秒、恢复3900秒。
测试fixture显式固定时间参数，避免用户本地调参影响回归。
使用临时验收脚本 /tmp/biwiki_real_model_e2e.py，通过ASGI HTTP客户端、真实已配置模型和
独立测试库随机schema，完成虚构MD上传→单指标提取→确定性校验PASS→待审批→测试批准→
知识列表/详情/Markdown/版本读取。提取22.57秒，最终succeeded。身份为测试注入，非真实MOA；
本轮不包含浏览器或代理，也未重跑用户原始长文。测试schema与Raw临时目录已清理，正式知识未改动。
uv run --locked pytest -q -p no:cacheprovider：117 passed；ruff check src tests通过。
需重启运行后端加载新的本地配置，并对用户原资料执行“重新生成”后人工审核。


2026-11-11 最新正式Ingest运行790.21秒后MODEL_OUTPUT_INVALID，模型调用已返回文本，失败在
Extraction Schema校验；先前实现未保留模型原文或校验明细，不能追溯具体违规字段。
Provider新增finish_reason=length/content_filter明确分类；Extractor错误提供最多5项已知Schema字段
位置和中文类型提示，未知键脱敏，不回显input/ctx/原始正文。提示词明确必填字段、属性字符串、
候选数量和纯JSON要求；未放宽Schema，未自动修复或重复调用模型。
119项回归测试通过，Ruff通过。该长文的具体错误原因仍需新请求的诊断结果，不能宣称已修复。


## S3 RawStore（2026-11-12）

用户授权参考老BI-WIKI扩展Raw存储；参考app/infra/storage/s3.py/factory.py的boto3+线程池模式。
新增RawStorage协议、S3RawStore及create_raw_store，默认local，lifespan选择并关闭。
S3参数包括bucket/prefix/endpoint/region/凭据/session token/addressing style；支持标准SDK凭据链。
使用IfNoneMatch=*条件创建，412核验既有对象；不自动建桶、不覆盖、不公开访问；128KiB读取上限和
SHA256复核，关闭响应体。409等错误明确失败，不回退无条件写入。服务层沿用线程池和MOA归属校验。
不改来源表，存储为部署级选择；已有Raw不自动迁移，切换需先复制并核验，未实施双读。
添加boto3依赖和锁文件。测试使用Stubber，不触及真实桶；S3与PostgreSQL接口集成通过。
发现用户新增extractor日志使用未定义logger且输出正文，保留日志意图改为字符数并导入logger。
全量128项通过，之后新增损坏对象及S3接口测试，专项11项通过；Ruff和diff检查通过。
真实S3/MinIO端到端未验证；默认本地配置未改，也未读取旧项目凭据。

2026-11-12 用户重新导入任务在902.86秒后MODEL_UNAVAILABLE，前一任务已succeeded。
同期最小HTTP模型探针200、2.12秒，当前基础连接可用；约15分钟耗时提示需查长请求连接中断，
既有记录未保存异常类型，不能断言具体网关限制。新增脱敏传输类型/耗时日志和错误提示，
区分ConnectError与RemoteProtocolError/ReadError；不记录正文、凭据、URL或原始异常消息。
