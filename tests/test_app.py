import asyncio
import logging
import unittest.mock

from async_app.app import App, Runnable, Service, make_service
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


class TestApp(TestCase):
    @fail_on(unused_loop=False)
    def test_config(self):
        class A(App):
            async def main(self):
                pass

        a = A(config=unittest.mock.sentinel.config)
        self.assertIs(a.config, unittest.mock.sentinel.config)

    @fail_on(unused_loop=False)
    def test_passing_event_loop(self):
        loop = asyncio.new_event_loop()

        async def foo():
            self.assertIs(asyncio.get_event_loop(), loop)

        App(target=foo).exec(loop=loop)

    def test_current_app(self):
        async def foo():
            self.assertIsNotNone(App.current_app())

        app = App(target=foo)

        with self.subTest('before exec'):
            self.assertIsNone(App.current_app())

        with self.subTest('exec'):
            app.exec()

        with self.subTest('after_exec'):
            self.assertIsNone(App.current_app())

        old_loop = asyncio.get_event_loop()
        asyncio.set_event_loop(None)

        with self.assertLogs('', logging.WARNING):
            self.assertIsNone(App.current_app())

        asyncio.set_event_loop(old_loop)

    def test_exec_exception(self):
        async def foo():
            raise RuntimeError

        async def bar():
            raise asyncio.CancelledError

        with self.assertRaises(RuntimeError):
            App(target=foo).exec()

        App(target=bar).exec()

    def test_exec_requires_target(self):
        with self.assertRaises(NotImplementedError):
            App(target=None).exec()

    @fail_on(unused_loop=False)
    def test_make_service(self):
        class AService(Service):
            async def main(self):
                pass

        class BService(Service):
            async def main(self):
                pass

        class MyApp(App):
            @make_service(AService)
            def _make_a_service(self, service_type, *args, **kwargs):
                return 'foo'

            @make_service(BService)
            def _make_b_service(self, service_type, *args, **kwargs):
                return 'bar'

        app = MyApp()
        self.assertEqual(app.make_service(AService), 'foo')
        self.assertEqual(app.make_service(BService), 'bar')
        self.assertEqual(app.make_service(int), int())
        self.assertIsNot(App._make_service_dispatcher, MyApp._make_service_dispatcher)


class TestService(TestCase):
    @fail_on(unused_loop=False)
    def test_config(self):
        class A(App):
            async def main(self):
                pass

        class S(Service):
            async def main(self):
                pass

        a = A(config=unittest.mock.sentinel.app_config)
        s = S(app=a)
        self.assertIs(s.config, a.config)

        s = S(app=a, config=unittest.mock.sentinel.service_config)
        self.assertIs(s.config, unittest.mock.sentinel.service_config)

    def test_resolves_app(self):
        test_self = self
        app = App()

        class S(Service):
            async def main(self):
                test_self.assertIs(self.app, app)

        async def foo():
            await S().start()

        app._target = foo
        app.exec()

    @fail_on(unused_loop=False)
    def test_make_service(self):
        class AService(Service):
            async def main(self):
                pass

        class BService(Service):
            async def main(self):
                pass

        class MyApp(App):
            @make_service(AService)
            def _make_a_service(self, service_type, *args, **kwargs):
                return 'foo'

        class MyService(Service):
            @make_service(BService)
            def _make_b_service(self, service_type, *args, **kwargs):
                return 'bar'

            async def main(self):
                pass

        service = MyService(app=MyApp())
        self.assertEqual(service.make_service(AService), 'foo')
        self.assertEqual(service.make_service(BService), 'bar')
        self.assertEqual(service.make_service(int), int())
        self.assertIsNot(Service._make_service_dispatcher, MyService._make_service_dispatcher)

        service = MyService()
        self.assertEqual(service.make_service(BService), 'bar')
        self.assertEqual(service.make_service(int), int())
