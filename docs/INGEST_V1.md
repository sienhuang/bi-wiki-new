# Ontology Ingest v1

日期：2026-11-10。基线：BIWIKI-ADS-BASELINE-001 V1.3。

## 使用流程

1. 后端配置模型并重启；前端MOA登录，打开「提取配置」设置业务要求、知识类型和数量。
2. 上传UTF-8 Markdown/TXT；原文按字节保存、按当前用户+SHA-256去重。
3. 点击「生成计划」；首次请求同步生成，最多135秒。超时/断线可以用相同请求键重试或查看任务列表。
4. 审核候选定义、原定义、字段差异、原文证据和未明确事项。确定性校验不证明语义正确。
5. 批准指定计划版本和哈希，或填写原因拒绝。批准整份计划；不支持部分发布。
6. 在知识库浏览正式定义、关系、Wiki文本及历史版本。

流程：登记来源 → 有界候选检索 → 结构化提取 → 校验 → 不可变计划 → 人工审批 → 事务发布。
首版执行为固定Workflow调用模型，不是自主Agent循环，不开放任意文件工具。

## 知识模型

ontology-v1含concept/entity/metric/rule/data_asset五类。每项有key、name、definition、scope、
attributes、unknowns、evidence、relations。key在个人空间唯一且稳定，更新不能改key或类型。
关系类型：measures（metric→entity）、constrained_by（→rule）、maps_to（→data_asset）、
depends_on、related_to。每条关系也需来源证据；不将普通相关关系解释为可执行JOIN。
证据包含来源ID、内容哈希、1起始行号和连续原文片段。JSON中的原文必须实际出现在该行范围内。
这只证明引用存在，不能证明结论被原文支持；语义审查为NOT_RUN，由审核人判断。
未明确事项原样保留。允许带unknowns发布，不能据此宣称定义可执行NL2SQL。

## 存储与版本

PostgreSQL是正式知识依据。ontology_definition保存当前定义及关系JSON，ontology_revision保存历史，
ontology_ingest保存计划、配置快照、审批、失败尝试，ontology_ingest_request保存幂等请求映射，
ontology_source记录Raw，ontology_config保存已发布的配置版本。沿用wiki_run，不改其已有列。
Markdown由结构化定义渲染，与定义和revision同事务保存，不另写wiki文件。
计划和Run结果本身即报告，可以从API取回。没有单独文件报告、wiki/log.md或文件目录索引。

原始文件保存在受管理的raw_root/owner_hash/content_hash，仅新增、不覆盖。文件名仅作显示，
不参与存储路径。上传不接受任意绝对/相对服务器路径；内部Raw访问拒绝不可信符号链接。
Raw文件落盘后数据库登记失败可能留存孤立文件；重传同内容会安全复用，首版不自动删除孤立Raw。
不同内容作为不同来源快照登记；尚无同一外部文档的自动版本链/定时同步。

当前初始化为幂等的新增表创建：默认initialize_database=true时启动建表；不需要新容器。
所有新增表可以在已有wiki_run旁创建。create_all不负责未来字段变更，后续须显式版本迁移。
备份须同时保留PostgreSQL和Raw目录；本版未实施生产备份恢复演练。

## 发布和恢复

计划固定version=1及内容哈希；重新生成会创建新Run，不原地更改计划。模型不能执行正式写入。
审批按服务端MOA UID检查空间归属，首版本人可审自己的计划，不宣称多人权限分离。
事务级PostgreSQL advisory lock串行化该空间的发布，行锁阻止重复审批。审核绑定哈希、版本，
检查Raw哈希和每个目标定义的预期版本；冲突409并要求重新生成。
所有定义及历史、审批决定、最终Run状态在一个事务中提交。事务内刷新数据再校验，异常整笔回滚。
发布失败保留awaiting_approval，另存最近20次失败尝试（时间、错误码、计划哈希），页面显示失败，
可以排查后重试或拒绝，不标记succeeded。未使用文件级多文件提交，因此不需要模拟文件替换Journal。
成功审批重复投递返回原结果，不生成重复revision；反向批准/拒绝返回409。

模型失败/结构非法/证据非法：Run failed，Raw保留；无候选或无变化：succeeded/no_change。
进程中断：列表、详情及新任务入口会对超过3分钟的running执行对账并标记failed/interrupted。
此为按访问触发的恢复，不是后台worker、自动重试或持久队列；服务正常执行总期限135秒。
客户端放弃等待不意味着服务端已停止，应先查看任务，不盲目换请求键重试。

## 配置与检索范围

个人空间的配置发布产生递增版本，后续任务使用新版本；旧Run保留完整配置快照和模型名。
可配置名称、提取类型、业务说明和最大候选数。Schema、工具能力和审批约束固定，不能由提示词关闭。
本版没有草稿配置管理、试运行模式、可视化拖拽、模型选择器、任意Schema编辑或候选手工编辑。
可通过生成待审计划评估规则效果，再拒绝不合适的计划。

候选检索：在当前用户定义中以来源文本匹配名称/key，最多提供30条摘要给模型；
确定性校验使用完整定义目录，不把全库正文放进模型。尚无全文/向量排序、规模压测或语义重复保证。
列表当前返回最近最多200条，前端名称/类型筛选在这批结果上进行；后续需分页与服务端搜索。

## API

所有响应为code/message/data/request_id/details。所有以下API都需X-MOA-Token。

| API | 行为 |
|---|---|
| POST /api/v1/sources | JSON filename/content_base64，保留原始字节；201，data.source及duplicate |
| GET /api/v1/sources | 当前用户最近200份来源 |
| GET /api/v1/sources/{id} | 来源元数据与原文 |
| GET/POST /api/v1/ingest-config | 读取当前配置/发布新版本 |
| POST /api/v1/ingests | source_id、UUID idempotency_key、可选reprocess；同步返回Run和计划 |
| GET /api/v1/ingests | 最近200项导入任务 |
| GET /api/v1/ingests/{id} | 来源、Run、配置快照、计划、审批、发布失败记录 |
| POST /api/v1/runs/{id}/approve | plan_version与plan_hash；批准并发布 |
| POST /api/v1/runs/{id}/reject | 上述字段及reason；拒绝计划 |
| GET /api/v1/definitions | 最近200项正式定义 |
| GET /api/v1/definitions/{id} | 定义、Wiki文本和历史版本 |

Query、独立Lint、通用Cancel仍为501。旧的source_ref Ingest输入已由受管理source_id替代。
跨用户访问不存在/无权资源均返回404；通用GET /runs也检查新Ingest归属。
旧通用任务登记接口仍只产生不含知识内容的空任务，不应拿它代替POST /ingests。

## 验证与限制

- 后端pytest：84 passed；真实PostgreSQL随机test schema，模型使用Fake/MockTransport。
- Ruff通过；前端TypeScript/Vite构建通过，工作台按需加载；存在约619KB工作台chunk体积警告。
- Playwright：9 passed，含8项MOA模拟回归和1项上传→审核→发布→知识浏览→配置完整模拟流程。
- 覆盖未审批无写入、哈希去重、请求幂等及别名、并发审批、拒绝、证据不匹配、关系错误、
  更新历史、旧版本冲突、模型错误、越权、符号链接、请求上限、写后失败整笔回滚与中断对账。
- 应用重启后来源、定义、历史和审批状态仍可读取。
- 真实Chromium → Vite5188 → FastAPI8029 → PostgreSQL隔离schema联调通过：上传、审核、发布、
  页面刷新、知识与任务历史读取。认证/提取模型为测试替身；API与数据库未模拟。
- 已核对真实联调审核页截图；临时前后端进程、测试schema和Raw已清理。
- 没有真实账号成功登录验收，没有真实模型提取质量评测，没有生产部署、队列或负载测试。

命令：`.venv/bin/pytest -q -p no:cacheprovider`、`.venv/bin/ruff check src tests`；
前端`npm run build`、`TEST_PORT=5187 npm test`。

隔离跨进程浏览器联调（模型与身份仍为测试替身）：
1. 后端运行`.venv/bin/python tests/serve_ingest_fixture.py`，绑定8029，自动使用独立测试库和临时Raw。
2. 前端运行`API_PROXY_TARGET=http://127.0.0.1:8029 npm run dev -- --port 5188`。
3. 前端运行`node tests/live-ingest.mjs`。
4. 用SIGTERM结束测试后端，使其清理自己创建的schema和临时Raw；停止5188测试前端。
不要将测试fixture作为真实服务启动；它不随wheel发布，认证替换仅存在于测试脚本。


## 2026-11-11 Provider 重构验收

新增 `src/bi_wiki/llm/{base,openai_compat,factory}.py`，调整 Extractor、应用装配和
任务模型快照；连接参数保持兼容。统一接口返回文本，业务负责领域结构校验。
新增 `tests/test_llm.py`；调整提取协议测试，新增网关403错误持久化到Run且无计划的测试。
测试配置显式禁用真实模型连接。初次全量回归发现既有未配置模型测试受本地.env影响，
修正隔离后重新执行 `uv run --locked pytest -q -p no:cacheprovider`：103 passed。
`uv run --locked ruff check src tests` 通过；模型测试使用替身，数据库回归使用真实独立测试库。
未验证真实模型成功提取；本轮不增加CLI、流式输出、重试、队列或新工作流。


### 通用配置与 CLI 补充

按用户最新决定移除旧配置名兼容，改用 BI_WIKI_LLM_*，添加 CLI Provider、工厂分支及
超时配置；本地.env只迁移字段名。README和.env.example提供两种Provider的配置。
新增tests/test_cli_provider.py，使用本地Python子进程验证标准输入、模型参数、stderr消费、
失败退出、输出大小、超时/取消回收和配置映射。完整pytest：115 passed；Ruff通过。
真实CLI模型未验证，未复制旧项目凭据。本节覆盖前文的旧配置兼容说明。


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
