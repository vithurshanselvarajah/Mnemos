"""Tests for the in-process WebSocket hub used by /ws/events."""

from __future__ import annotations

import asyncio
from unittest import mock


def _make_async_ws():
    ws = mock.MagicMock()
    ws.accept = mock.AsyncMock()
    ws.send_text = mock.AsyncMock()
    ws.send_bytes = mock.AsyncMock()
    ws.close = mock.AsyncMock()
    return ws


def test_publish_without_loop_logs_warning(backend_imports, caplog):
    from app.services import websocket_hub

    websocket_hub._loop = None
    with caplog.at_level("WARNING", logger="mnemos.ws"):
        websocket_hub.publish({"type": "x"})
    assert any("no loop bound" in r.getMessage() for r in caplog.records)


def test_publish_with_loop_dispatches_to_clients(backend_imports):
    from app.services import websocket_hub

    async def _run():
        loop = asyncio.get_running_loop()
        websocket_hub.bind_loop(loop)
        ws1 = _make_async_ws()
        ws2 = _make_async_ws()
        websocket_hub._clients.clear()
        websocket_hub._clients.add(ws1)
        websocket_hub._clients.add(ws2)
        websocket_hub.publish({"type": "test.event", "x": 1})
        for _ in range(20):
            await asyncio.sleep(0.01)
            if ws1.send_text.await_count > 0 and ws2.send_text.await_count > 0:
                break
        websocket_hub._clients.clear()
        return ws1.send_text.await_args_list + ws2.send_text.await_args_list

    calls = asyncio.run(_run())
    assert any("test.event" in (c.args[0] if c.args else "") for c in calls)


def test_publish_handles_dead_client_without_raising(backend_imports):
    from app.services import websocket_hub

    async def _run():
        loop = asyncio.get_running_loop()
        websocket_hub.bind_loop(loop)
        ws = _make_async_ws()
        ws.send_text.side_effect = RuntimeError("dead")
        websocket_hub._clients.clear()
        websocket_hub._clients.add(ws)
        websocket_hub.publish({"type": "dead.test"})
        for _ in range(20):
            await asyncio.sleep(0.01)
            if ws.send_text.await_count > 0:
                break
        return list(websocket_hub._clients)

    asyncio.run(_run())


def test_publish_drops_client_when_rct_raises(backend_imports):
    from app.services import websocket_hub

    async def _run():
        loop = asyncio.get_running_loop()
        websocket_hub.bind_loop(loop)
        websocket_hub._clients.clear()
        ws = _make_async_ws()
        websocket_hub._clients.add(ws)
        with mock.patch(
            "app.services.websocket_hub.asyncio.run_coroutine_threadsafe",
            side_effect=RuntimeError("loop closed"),
        ):
            websocket_hub.publish({"type": "boom.test"})
        return list(websocket_hub._clients)

    leftover = asyncio.run(_run())
    assert leftover == []


def test_register_replays_recent(backend_imports):
    from app.services import websocket_hub

    async def _run():
        websocket_hub._RECENT.clear()
        websocket_hub._RECENT.append({"type": "old"})
        ws = _make_async_ws()
        await websocket_hub.register(ws)
        await websocket_hub.unregister(ws)
        return ws.send_text.await_args_list

    calls = asyncio.run(_run())
    assert any("old" in (c.args[0] if c.args else "") for c in calls)


def test_register_swallows_send_errors(backend_imports):
    from app.services import websocket_hub

    async def _run():
        websocket_hub._RECENT.clear()
        websocket_hub._RECENT.append({"type": "stale"})
        ws = _make_async_ws()
        ws.send_text.side_effect = RuntimeError("nope")
        await websocket_hub.register(ws)
        return ws in websocket_hub._clients

    still_in = asyncio.run(_run())
    assert still_in is False


def test_unregister_removes_client(backend_imports):
    from app.services import websocket_hub

    async def _run():
        ws = _make_async_ws()
        websocket_hub._clients.clear()
        websocket_hub._clients.add(ws)
        await websocket_hub.unregister(ws)
        return list(websocket_hub._clients)

    leftover = asyncio.run(_run())
    assert leftover == []


def test_recent_returns_snapshot(backend_imports):
    from app.services import websocket_hub

    websocket_hub._RECENT.clear()
    websocket_hub._RECENT.append({"type": "a"})
    websocket_hub._RECENT.append({"type": "b"})
    out = websocket_hub.recent()
    assert out == [{"type": "a"}, {"type": "b"}]


def test_recent_is_bounded(backend_imports):
    from app.services import websocket_hub

    websocket_hub._RECENT.clear()
    for i in range(200):
        websocket_hub._RECENT.append({"type": str(i)})
    assert len(websocket_hub._RECENT) == 64
    assert websocket_hub._RECENT[0]["type"] == str(200 - 64)


def test_publish_skipped_when_no_clients(backend_imports):
    from app.services import websocket_hub

    async def _run():
        loop = asyncio.get_running_loop()
        websocket_hub.bind_loop(loop)
        websocket_hub._clients.clear()
        websocket_hub.publish({"type": "no.client.test"})
        await asyncio.sleep(0.01)
        return True

    asyncio.run(_run())


def test_bind_loop_records_loop(backend_imports):
    from app.services import websocket_hub

    async def _run():
        loop = asyncio.get_running_loop()
        websocket_hub.bind_loop(loop)
        return websocket_hub._loop

    got = asyncio.run(_run())
    assert got is not None
