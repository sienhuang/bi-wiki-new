# bi_wiki 协作约定

修改前先读取 docs/PROJECT_MEMORY.md 和 docs/Agent_Service_Master_Specification.md，并检查 git status。
保留已有用户修改。当前范围为阶段 1，以及用户明确授权的 MOA 认证与独立前端登录壳；不自动进入知识工作流阶段。

- 使用 PostgreSQL 作为运行与测试数据库。测试必须显式配置独立 *_test 库，执行 DDL 前验证范围。
- 知识资产与服务代码分开；当前服务启动和预留 API 不应读取或写入 knowledge。
- API、任务契约、持久化和公共配置各自承担职责，不在路由中塞入模型或文件操作。
- 任务状态必须真实。未实现工作流返回 FEATURE_NOT_IMPLEMENTED，不生成虚假执行结果。
- 数据库 URL、密钥和私有正文不进入 Git、日志或错误响应；不读取旧项目凭据作为默认值。
- 使用 uv.lock 复现依赖，修改后运行相关测试及 Ruff。Mock/故障注入与真实 PostgreSQL 验证分开记录。
- Ontology 元模型、Runtime、队列和知识发布政策尚未确定，不能默认为每条知识自动发布或一律人工审批。
- 形成稳定决策或已验证事实后更新项目记忆和阶段报告；不记录凭据和临时噪声。



2026-11-10 用户已授权 Ontology Ingest 首版，覆盖上文阶段1限制。当前基线 V1.3，详见
 docs/INGEST_V1.md。修改须保留个人空间隔离、Raw 不可变、固定版本审批及事务发布。
本版正式知识在 PostgreSQL，Markdown 是派生展示文本；不额外创建平行事实存储。
