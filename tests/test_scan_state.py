"""Тесты состояния сканирования: прогресс, защита от двойного запуска."""

from __future__ import annotations

from app.scanner.state import ScanState


async def test_begin_blocks_second_run():
    """Две вкладки не должны запускать два скана одновременно."""
    state = ScanState()
    assert await state.begin("full") is True
    assert await state.begin("incremental") is False
    assert state.status == "running"


async def test_progress_from_events():
    state = ScanState()
    await state.begin("incremental")
    state.update({"stage": "walk_done", "run_id": 7, "seen": 100, "to_parse": 40})
    assert state.percent == 0.0
    state.update({"stage": "parsing", "total": 40, "processed": 10, "added": 3})
    assert state.percent == 25.0
    assert state.added == 3
    state.update({"stage": "parsing", "total": 40, "processed": 40})
    assert state.percent == 100.0


async def test_finish_releases_lock():
    state = ScanState()
    await state.begin("full")
    await state.finish(status="completed")
    assert state.status == "completed"
    assert state.percent == 100.0
    # После завершения можно запускать снова.
    assert await state.begin("full") is True


async def test_fail_records_error():
    state = ScanState()
    await state.begin("full")
    await state.fail("нет доступа к каталогу")
    assert state.status == "failed"
    assert "каталог" in state.error
    assert state.as_dict()["error"]


async def test_no_progress_without_total():
    """Пока не известен объём, процент не должен прыгать в 100."""
    state = ScanState()
    await state.begin("full")
    state.update({"stage": "walk"})
    assert state.percent == 0.0
