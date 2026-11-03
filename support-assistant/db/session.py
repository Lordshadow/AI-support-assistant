"""
Database Session Management with PostgreSQL RLS Tenant Context.
Complies with Specification Sections 6, 10, and 15.1.8.
"""

import os
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncIterator, Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker
)

from db.models import Base

DEFAULT_ASYNC_URL = os.environ.get(
    "DATABASE_ASYNC_URL",
    os.environ.get("DATABASE_URL", "postgresql+asyncpg://novaretail_app:novaretail_app_secret@localhost:5432/novaretail")
)
DEFAULT_SYNC_URL = os.environ.get(
    "DATABASE_SYNC_URL",
    DEFAULT_ASYNC_URL.replace("+asyncpg", "+psycopg2").replace("+aiosqlite", "")
)

# Global engine singletons (lazily initialized or configurable)
_async_engine = None
_async_session_factory = None
_sync_engine = None
_sync_session_factory = None


def get_async_engine(url: Optional[str] = None):
    global _async_engine, _async_session_factory
    target_url = url or DEFAULT_ASYNC_URL
    if _async_engine is None or url is not None:
        engine = create_async_engine(
            target_url,
            echo=False,
            future=True,
            pool_pre_ping=True
        )
        if url is None:
            _async_engine = engine
            _async_session_factory = async_sessionmaker(
                bind=_async_engine,
                expire_on_commit=False,
                class_=AsyncSession
            )
        return engine
    return _async_engine


def get_sync_engine(url: Optional[str] = None):
    global _sync_engine, _sync_session_factory
    target_url = url or DEFAULT_SYNC_URL
    if _sync_engine is None or url is not None:
        engine = create_engine(
            target_url,
            echo=False,
            future=True,
            pool_pre_ping=True
        )
        if url is None:
            _sync_engine = engine
            _sync_session_factory = sessionmaker(
                bind=_sync_engine,
                expire_on_commit=False
            )
        return engine
    return _sync_engine


@asynccontextmanager
async def get_async_session(
    tenant_id: Optional[str] = None,
    engine=None
) -> AsyncIterator[AsyncSession]:
    """
    Async context manager yielding an AsyncSession with tenant RLS set.
    Executes `SELECT set_config('app.tenant_id', :t, true)` within the transaction.
    """
    eng = engine or get_async_engine()
    session_factory = async_sessionmaker(bind=eng, expire_on_commit=False, class_=AsyncSession)
    
    async with session_factory() as session:
        async with session.begin():
            if tenant_id:
                if eng.dialect.name == "postgresql":
                    await session.execute(
                        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                        {"tenant_id": tenant_id}
                    )
                else:
                    session.info["tenant_id"] = tenant_id
            try:
                yield session
            except Exception:
                await session.rollback()
                raise


@contextmanager
def get_sync_session(
    tenant_id: Optional[str] = None,
    engine=None
) -> Iterator[Session]:
    """
    Sync context manager yielding a Session with tenant RLS set.
    """
    eng = engine or get_sync_engine()
    session_factory = sessionmaker(bind=eng, expire_on_commit=False)
    
    with session_factory() as session:
        with session.begin():
            if tenant_id:
                if eng.dialect.name == "postgresql":
                    session.execute(
                        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                        {"tenant_id": tenant_id}
                    )
                else:
                    session.info["tenant_id"] = tenant_id
            try:
                yield session
            except Exception:
                session.rollback()
                raise


async def create_tables_async(engine):
    """Utility to create schema on test or development databases."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def create_tables_sync(engine):
    """Utility to create schema on sync test databases."""
    Base.metadata.create_all(bind=engine)
