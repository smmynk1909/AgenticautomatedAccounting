import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from awp_mcp_base.repo import RepoBase
from awp_mcp_base.tests.conftest import widgets_table
from awp_mcp_base.uow import UnitOfWork


class WidgetRepo(RepoBase):
    table = widgets_table


@pytest.mark.asyncio
async def test_get_returns_none_for_missing_row(sqlite_engine: AsyncEngine) -> None:
    uow = UnitOfWork(sqlite_engine)
    async with uow() as session:
        row = await WidgetRepo(session).get(999)
    assert row is None


@pytest.mark.asyncio
async def test_update_stamps_updated_at_automatically(sqlite_engine: AsyncEngine) -> None:
    uow = UnitOfWork(sqlite_engine)
    async with uow() as session:
        repo = WidgetRepo(session)
        pk = await repo.insert({"name": "widget-1"})
        await repo.update(pk, {"name": "widget-1-renamed"})

    async with uow() as session:
        row = await WidgetRepo(session).get(pk)
    assert row is not None
    assert row["name"] == "widget-1-renamed"
    assert row["updated_at"] is not None


@pytest.mark.asyncio
async def test_soft_delete_hides_row_by_default_but_keeps_it_on_request(
    sqlite_engine: AsyncEngine,
) -> None:
    uow = UnitOfWork(sqlite_engine)
    async with uow() as session:
        repo = WidgetRepo(session)
        pk = await repo.insert({"name": "widget-1"})
        await repo.soft_delete(pk)

    async with uow() as session:
        repo = WidgetRepo(session)
        assert await repo.get(pk) is None
        row = await repo.get(pk, include_deleted=True)
    assert row is not None
    assert row["deleted_at"] is not None
