import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from awp_mcp_base.repo import RepoBase
from awp_mcp_base.tests.conftest import widgets_table
from awp_mcp_base.uow import UnitOfWork


class WidgetRepo(RepoBase):
    table = widgets_table


@pytest.mark.asyncio
async def test_uow_commits_on_success(sqlite_engine: AsyncEngine) -> None:
    uow = UnitOfWork(sqlite_engine)
    async with uow() as session:
        pk = await WidgetRepo(session).insert({"name": "widget-1"})

    async with uow() as session:
        row = await WidgetRepo(session).get(pk)
    assert row is not None
    assert row["name"] == "widget-1"


@pytest.mark.asyncio
async def test_uow_rolls_back_on_exception(sqlite_engine: AsyncEngine) -> None:
    uow = UnitOfWork(sqlite_engine)
    with pytest.raises(RuntimeError):
        async with uow() as session:
            await WidgetRepo(session).insert({"name": "widget-2"})
            raise RuntimeError("boom mid-transaction")

    async with uow() as session:
        result = await session.execute(select(widgets_table))
        assert result.mappings().first() is None
