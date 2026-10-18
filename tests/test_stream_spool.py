"""Offline streaming regressions: local fixtures only, no Telegram or secrets."""

import asyncio
import importlib.util
import logging
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


def load_spool():
    bot = types.ModuleType("bobby")
    bot.logger = logging.getLogger("spool-test")
    path = Path(__file__).resolve().parents[1] / "bobby/core/spool.py"
    spec = importlib.util.spec_from_file_location("spool_test_module", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"bobby": bot}):
        spec.loader.exec_module(module)
    return module


class StreamSpoolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mod = load_spool()
        self.mod._RANGE_SETTLE = 0.01
        self.mod._STALL_TIMEOUT = 0.5
        self.entry = self.mod._Entry("test", ("fixture",))
        self.spool = self.mod.StreamSpool()
        app = web.Application()

        async def serve(request):
            return await self.spool._stream(request, self.entry)

        app.router.add_get("/", serve)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_pending_range_waits_for_producer_not_502(self):
        self.entry.buf.extend(b"first")

        async def producer():
            await asyncio.sleep(0.06)
            self.entry.buf.extend(b"-next")
            await self.entry._notify()

        task = asyncio.create_task(producer())
        async with self.client.get("/", headers={"Range": "bytes=5-"}) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers["Content-Range"], "bytes 5-9/*")
            self.assertEqual(await response.read(), b"-next")
        await task

    async def test_waiting_range_becomes_true_eof(self):
        self.entry.buf.extend(b"first")

        async def producer():
            await asyncio.sleep(0.04)
            await self.entry._finish()

        task = asyncio.create_task(producer())
        async with self.client.get("/", headers={"Range": "bytes=5-"}) as response:
            self.assertEqual(response.status, 416)
            self.assertEqual(response.headers["Content-Range"], "bytes */5")
        await task

    async def test_failed_producer_is_not_clean_eof(self):
        self.entry.buf.extend(b"partial")
        await self.entry._finish("producer failed")
        async with self.client.get("/") as response:
            with self.assertRaises(aiohttp.ClientPayloadError):
                await response.read()
        async with self.client.get("/", headers={"Range": "bytes=7-"}) as response:
            self.assertEqual(response.status, 502)

    async def test_stalled_range_is_bounded(self):
        self.mod._STALL_TIMEOUT = 0.03
        self.entry.buf.extend(b"partial")
        async with self.client.get("/", headers={"Range": "bytes=7-"}) as response:
            self.assertEqual(response.status, 504)

    async def test_finite_ranges_are_exact_and_eof_is_immediate(self):
        self.entry.buf.extend(bytes(range(256)) * 20)
        await self.entry._finish()
        for header, start, end in (("bytes=0-", 0, 5120),
                                    ("bytes=77-198", 77, 199),
                                    ("bytes=-100", 5020, 5120)):
            async with self.client.get("/", headers={"Range": header}) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(await response.read(), bytes(self.entry.buf[start:end]))
                self.assertEqual(int(response.headers["Content-Length"]), end - start)
        for start in (5120, 6000):
            before = time.monotonic()
            async with self.client.get("/", headers={"Range": f"bytes={start}-"}) as response:
                self.assertEqual(response.status, 416)
                self.assertLess(time.monotonic() - before, 0.5)

    async def test_prime_rejects_empty_completed_source(self):
        await self.entry._finish()
        with patch.object(self.spool, "_ensure", return_value=self.entry):
            self.assertFalse(await self.spool._prime("test", timeout=0.1))
        self.entry.buf.extend(b"audio")
        with patch.object(self.spool, "_ensure", return_value=self.entry):
            self.assertTrue(await self.spool._prime("test", timeout=0.1))

    async def test_producer_exit_between_poll_and_kill_is_reaped(self):
        proc = types.SimpleNamespace(
            returncode=None,
            kill=Mock(side_effect=ProcessLookupError),
            wait=AsyncMock(),
        )

        await self.mod._stop_process(proc)

        proc.kill.assert_called_once()
        proc.wait.assert_awaited_once()

    async def test_spool_keeps_serving_when_bot_loop_is_blocked(self):
        """The production server runs on its own loop, not the bot event loop."""
        payload = bytes(range(256)) * 1024
        producer_app = web.Application()

        async def source(request):
            return web.Response(body=payload)

        producer_app.router.add_get("/", source)
        server = TestServer(producer_app)
        await server.start_server()
        spool = self.mod.StreamSpool()
        try:
            url = await spool.wrap(str(server.make_url("/")))
            self.assertTrue(await spool.prime(url))

            async def wait_done():
                entry = next(iter(spool._entries.values()))
                async with entry.cond:
                    await asyncio.wait_for(entry.cond.wait_for(lambda: entry.done), 2)

            await spool._on_spool(wait_done())
            # Do the HTTP read in another thread while this bot loop is
            # deliberately blocked. Neither the producer nor reader should
            # need the bot event loop once the source is buffered.
            import concurrent.futures
            import urllib.request

            def read():
                with urllib.request.urlopen(url, timeout=1) as response:
                    return response.read()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(read)
                time.sleep(0.15)
                self.assertTrue(future.done(), "spool was blocked by the bot event loop")
                self.assertEqual(future.result(), payload)
        finally:
            async def cleanup():
                current = asyncio.current_task()
                tasks = [t for t in asyncio.all_tasks() if t is not current]
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if spool._runner:
                    await spool._runner.cleanup()

            if spool._loop is not None:
                await spool._on_spool(cleanup())
                spool._loop.call_soon_threadsafe(spool._loop.stop)
            await server.close()


if __name__ == "__main__":
    unittest.main()