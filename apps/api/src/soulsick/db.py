from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str):
        self.engine: AsyncEngine = create_async_engine(url)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

        @event.listens_for(self.engine.sync_engine, "connect")
        def _pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    async def create_all(self) -> None:
        from . import models  # noqa: F401  (enregistre les tables)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_add_missing_columns)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as s:
            yield s

    async def dispose(self) -> None:
        await self.engine.dispose()


def _add_missing_columns(conn) -> None:
    """Migration minimale : ajoute les colonnes apparues dans le modèle depuis la création de la base.

    Seules les colonnes avec une valeur par défaut serveur (ou nullables) sont ajoutées ;
    les données existantes ne sont jamais modifiées.
    """
    from sqlalchemy import inspect

    insp = inspect(conn)
    for table in Base.metadata.sorted_tables:
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(conn.dialect)}'
            if col.server_default is not None:
                ddl += f" DEFAULT {col.server_default.arg}"
            conn.exec_driver_sql(ddl)
