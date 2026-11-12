from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bi_wiki.core.config import Settings
from bi_wiki.db.models import Base, RunORM
from bi_wiki.ingest import tables


class Database:
    def __init__(self, settings: Settings) -> None:
        self.engine = create_async_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={
                "timeout": settings.database_timeout_seconds,
                "command_timeout": settings.database_timeout_seconds,
                "server_settings": {"search_path": settings.database_schema},
            },
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def initialize(self) -> None:
        # 第一阶段只创建本服务的新表；已有结构变更应在后续通过显式迁移管理。
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def check(self) -> None:
        # 检查实际数据库与任务表，而非返回一个与存储无关的固定 healthy。
        async with self.engine.connect() as connection:
            await connection.execute(select(RunORM.run_id).limit(1))
            for model in (
                tables.SourceORM,
                tables.ConfigORM,
                tables.IngestORM,
                tables.DefinitionORM,
                tables.RevisionORM,
                tables.RequestORM,
            ):
                await connection.execute(select(model).limit(0))

    async def close(self) -> None:
        await self.engine.dispose()
