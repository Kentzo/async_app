import asyncio
import logging
import unittest.mock

from async_app.app import Runnable
from asynctest import TestCase, fail_on

from . import with_timeout


class StubRunnable(Runnable):
    async def main(self):
        pass


class RaisingStubRunnable(Runnable):
    async def main(self):
        raise RuntimeError()


class TestRunnable(TestCase):
    def assert_is_not_running(self, runnable):
        self.assertFalse(runnable.is_alive)
        self.assertFalse(runnable.is_done)

    def assert_is_alive(self, runnable):
        self.assertTrue(runnable.is_alive)
        self.assertFalse(runnable.is_done)

    def assert_is_done(self, runnable):
        self.assertFalse(runnable.is_alive)
        self.assertTrue(runnable.is_done)
        self.assertTrue(runnable.should_stop)
        self.assertFalse(runnable.is_aborted)

    def assert_is_aborted(self, runnable):
        self.assertFalse(runnable.is_alive)
        self.assertTrue(runnable.is_done)
        self.assertTrue(runnable.should_stop)
        self.assertTrue(runnable.is_aborted)

    @with_timeout()
    async def test_initialize_sets_is_initialized(self):
        r = StubRunnable()

        self.assert_is_not_running(r)
        r.start()
        self.assert_is_alive(r)
        await r
        self.assert_is_done(r)

        self.assertTrue(r.is_initialized)

    @with_timeout()
    async def test_abort(self):
        with self.subTest('before_start'):
            r = StubRunnable()
            r.stop = unittest.mock.Mock(wraps=r.stop)

            self.assert_is_not_running(r)
            r.abort()
            self.assert_is_not_running(r)
            self.assertTrue(r.is_aborted)

            r.stop.assert_called_once()

        with self.subTest('during_main'):
            r = StubRunnable()
            r.stop = unittest.mock.Mock(wraps=r.stop)

            self.assert_is_not_running(r)
            r.start()
            self.assert_is_alive(r)
            await asyncio.sleep(0)
            r.abort()

            self.assertTrue(r.is_aborted)
            r.stop.assert_called_once()

            with self.assertRaises(asyncio.CancelledError):
                await r

            self.assert_is_aborted(r)

        with self.subTest('after_cleanup'):
            r = StubRunnable()
            r.stop = unittest.mock.Mock(wraps=r.stop)

            self.assert_is_not_running(r)
            r.start()
            self.assert_is_alive(r)
            await r
            r.abort()
            self.assert_is_aborted(r)

            r.stop.assert_called_once()

    @with_timeout()
    async def test_stop(self):
        with self.subTest('before_start'):
            r = StubRunnable()

            self.assert_is_not_running(r)
            r.stop()
            self.assert_is_not_running(r)
            r.start()
            self.assert_is_alive(r)
            self.assertTrue(r.should_stop)

            with self.assertRaises(asyncio.CancelledError):
                await r

            self.assert_is_done(r)

        with self.subTest('during_main'):
            class R(Runnable):
                async def main(self):
                    await asyncio.sleep(60)

            r = R()
            self.assert_is_not_running(r)
            r.start()
            self.assert_is_alive(r)

            await asyncio.sleep(0)

            r.stop()
            self.assert_is_alive(r)
            self.assertTrue(r.should_stop)

            with self.assertRaises(asyncio.CancelledError):
                await r

            self.assertTrue(r._run_f.cancelled())
            self.assert_is_done(r)

        with self.subTest('after_cleanup'):
            r = StubRunnable()

            self.assert_is_not_running(r)
            r.start()
            self.assert_is_alive(r)
            await r
            self.assert_is_done(r)
            r.stop()
            self.assert_is_done(r)

            self.assertFalse(r._run_f.cancelled())

    @with_timeout()
    async def test_implicit_stop_sets_should_stop(self):
        with self.subTest('normal'):
            r = StubRunnable()

            self.assert_is_not_running(r)
            r.start()
            self.assert_is_alive(r)
            await r
            self.assert_is_done(r)

        with self.subTest('exception'):
            r = RaisingStubRunnable()

            self.assert_is_not_running(r)
            r.start()
            self.assert_is_alive(r)

            with self.assertRaises(RuntimeError):
                await r

            self.assert_is_aborted(r)

    @with_timeout()
    async def test_initialize_called_before_main(self):
        r = StubRunnable()
        r.initialize = unittest.mock.Mock(wraps=r.initialize)
        r.main = unittest.mock.Mock(wraps=r.main)

        m = unittest.mock.Mock()
        m.m0, m.m1 = r.initialize, r.main

        self.assert_is_not_running(r)
        r.start()
        self.assert_is_alive(r)
        await r
        self.assert_is_done(r)

        m.assert_has_calls([unittest.mock.call.m0(), unittest.mock.call.m1()])

    @with_timeout()
    async def test_cleanup_called_after_main(self):
        r = StubRunnable()
        r.main = unittest.mock.Mock(wraps=r.main)
        r.cleanup = unittest.mock.Mock(wraps=r.cleanup)

        m = unittest.mock.Mock()
        m.m0, m.m1 = r.main, r.cleanup

        self.assert_is_not_running(r)
        r.start()
        self.assert_is_alive(r)
        await r
        self.assert_is_done(r)

        m.assert_has_calls([unittest.mock.call.m0(), unittest.mock.call.m1()])

    @with_timeout()
    async def test_main_and_cleanup_not_called_when_initialize_fails(self):
        class R(Runnable):
            async def initialize(self):
                raise RuntimeError()

            async def main(self):
                pass

        r = R()
        r.initialize = unittest.mock.Mock(wraps=r.initialize)
        r.main = unittest.mock.Mock(wraps=r.main)
        r.cleanup = unittest.mock.Mock(wraps=r.cleanup)

        self.assert_is_not_running(r)
        r.start()
        self.assert_is_alive(r)
        with self.assertRaises(RuntimeError):
            await r

        self.assert_is_aborted(r)

        r.initialize.assert_called_once()
        r.main.assert_not_called()
        r.cleanup.assert_not_called()

    @with_timeout()
    async def test_cleanup_is_called_if_main_fails(self):
        r = RaisingStubRunnable()
        r.initialize = unittest.mock.Mock(wraps=r.initialize)
        r.main = unittest.mock.Mock(wraps=r.main)
        r.cleanup = unittest.mock.Mock(wraps=r.cleanup)

        self.assert_is_not_running(r)
        r.start()
        self.assert_is_alive(r)

        with self.assertRaises(RuntimeError):
            await r._run_f

        self.assert_is_aborted(r)

        r.initialize.assert_called_once()
        r.main.assert_called_once()
        r.cleanup.assert_called_once()

    @with_timeout()
    async def test_cleanup_is_called_if_main_succeeds(self):
        r = StubRunnable()
        r.initialize = unittest.mock.Mock(wraps=r.initialize)
        r.main = unittest.mock.Mock(wraps=r.main)
        r.cleanup = unittest.mock.Mock(wraps=r.cleanup)

        self.assert_is_not_running(r)
        r.start()
        self.assert_is_alive(r)
        await r
        self.assert_is_done(r)

        r.initialize.assert_called_once()
        r.main.assert_called_once()
        r.cleanup.assert_called_once()

    @with_timeout()
    async def test_start_cannot_be_called_twice(self):
        r = StubRunnable()
        r.start()

        with self.assertRaises(RuntimeError):
            r.start()

        self.assert_is_alive(r)
        await r
        self.assert_is_done(r)

    @with_timeout()
    async def test_await_raises_if_not_running(self):
        r = StubRunnable()

        self.assert_is_not_running(r)

        with self.assertRaises(RuntimeError):
            await r

    @with_timeout()
    async def test_abort_from_initialize(self):
        class R(Runnable):
            async def initialize(self):
                self.abort()

            async def main(self):
                pass

        r = R()
        r.initialize = unittest.mock.Mock(wraps=r.initialize)
        r.main = unittest.mock.Mock(wraps=r.main)
        r.cleanup = unittest.mock.Mock(wraps=r.cleanup)

        self.assert_is_not_running(r)
        r.start()
        self.assert_is_alive(r)

        with self.assertRaises(asyncio.CancelledError):
            await r

        self.assert_is_aborted(r)

        r.initialize.assert_called_once()
        r.main.assert_not_called()
        r.cleanup.assert_not_called()

        self.assertFalse(r.is_initialized)

    @with_timeout()
    async def test_completion_sets_is_done(self):
        r = StubRunnable()

        self.assert_is_not_running(r)
        r.start()
        self.assert_is_alive(r)
        await r
        self.assert_is_done(r)

    @fail_on(unused_loop=False)
    def test_LOG(self):
        with self.subTest('derived'):
            class A(Runnable):
                pass

            class B(A):
                pass

            self.assertEqual(A.LOG, logging.getLogger('{}.{}'.format(A.__module__, A.__qualname__)))
            self.assertEqual(B.LOG, logging.getLogger('{}.{}'.format(B.__module__, B.__qualname__)))

        with self.subTest('override'):
            l = logging.getLogger('mylogger')

            class A(Runnable):
                pass

            class B(A):
                LOG = l.getChild('42')

            self.assertEqual(B.LOG, l.getChild('42'))

    @with_timeout()
    async def test_initialize_must_call_super(self):
        class R(Runnable):
            async def initialize(self):
                pass

            async def main(self):
                pass

        r = R()

        self.assert_is_not_running(r)
        r.start()
        self.assert_is_alive(r)

        with self.assertRaises(NotImplementedError):
            await r

        self.assert_is_aborted(r)

    @with_timeout()
    async def test_context_manager(self):
        class R(Runnable):
            async def main(self):
                await asyncio.sleep(60)

        r = R()

        self.assert_is_not_running(r)

        async with r:
            self.assert_is_alive(r)

        self.assert_is_done(r)

    @with_timeout()
    async def test_task_can_be_manually_cancelled(self):
        r = StubRunnable()

        self.assert_is_not_running(r)
        r.start()
        self.assert_is_alive(r)
        r._run_f.cancel()
        self.assert_is_alive(r)

        with self.assertRaises(asyncio.CancelledError):
            await r

        self.assert_is_done(r)
