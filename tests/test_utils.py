import asyncio
import unittest.mock

from async_app.utils import AsyncExitStack, TaskGroup, wait_one
from asynctest import TestCase, fail_on

from . import with_timeout


class TestTaskGroup(TestCase):
    @with_timeout()
    async def test_removal_of_completed_tasks(self):
        async with TaskGroup() as tasks:
            tasks.remove_task = unittest.mock.MagicMock(wraps=tasks.remove_task)
            t = tasks.add_task(asyncio.sleep(0.01))
            await t
            tasks.remove_task.assert_called_once_with(t)

    @with_timeout()
    async def test_collection_integrity(self):
        async with TaskGroup() as tasks:
            t = tasks.add_task(asyncio.sleep(0.01))
            self.assertIn(t, tasks)
            await t
            self.assertNotIn(t, tasks)

    @with_timeout()
    async def test_len(self):
        async with TaskGroup() as tasks:
            t = tasks.add_task(asyncio.sleep(0.01))
            self.assertEqual(len(tasks), 1)
            await t
            self.assertEqual(len(tasks), 0)

    @with_timeout()
    async def test_enumeration(self):
        async with TaskGroup() as tasks:
            tasks.add_task(asyncio.sleep(0.01))

            for t in tasks:
                self.assertIn(t, tasks)
                await t
                self.assertNotIn(t, tasks)

    @with_timeout()
    async def test_cancellation(self):
        async with TaskGroup() as tasks:
            t1 = tasks.add_task(asyncio.sleep(0.01))
            t2 = tasks.add_task(asyncio.sleep(60))

            await t1

        self.assertTrue(t2.cancelled())


class TestWaitOne(TestCase):
    @with_timeout()
    async def test_await_first_return(self):
        async with TaskGroup() as tasks:
            e1 = asyncio.Event()
            e2 = asyncio.Event()

            e1_task = tasks.add_task(e1.wait())
            e2_task = tasks.add_task(e2.wait())
            wait_one_task = asyncio.ensure_future(wait_one(e1_task, e2_task))

            e1.set()
            await wait_one_task

            self.assertTrue(e1_task.done())
            self.assertFalse(e2_task.done())

    @with_timeout()
    async def test_await_first_exception(self):
        async with TaskGroup() as tasks:
            f1 = asyncio.Future()
            f2 = asyncio.Future()

            f1_task = tasks.add_task(f1)
            f2_task = tasks.add_task(f2)
            wait_one_task = asyncio.ensure_future(wait_one(f1_task, f2_task))

            await asyncio.sleep(0)  # give loop a chance to schedule futures
            self.assertFalse(f1_task.done())
            self.assertFalse(f2_task.done())
            f1_task.set_exception(RuntimeError())

            with self.assertRaises(RuntimeError):
                await wait_one_task

            self.assertIsInstance(wait_one_task.exception(), RuntimeError)
            self.assertTrue(f1_task.done())
            self.assertFalse(f2_task.done())


class TeatAsyncExitStack(TestCase):
    @with_timeout()
    async def test_order(self):
        class AsyncContext:
            def __init__(self, enter_queue, exit_queue):
                self.enter_queue = enter_queue
                self.exit_queue = exit_queue

            async def __aenter__(self):
                self.enter_queue.append(self)
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_queue.append(self)

        enter_queue = []
        exit_queue = []

        a = AsyncContext(enter_queue, exit_queue)
        b = AsyncContext(enter_queue, exit_queue)
        c = AsyncContext(enter_queue, exit_queue)

        async with AsyncExitStack() as stack:
            await stack.enter_context(a)
            await stack.enter_context(b)
            await stack.enter_context(c)

        self.assertListEqual(enter_queue, [a, b, c])
        self.assertListEqual(exit_queue, [c, b, a])

    @with_timeout()
    async def test_deadlock(self):
        class AsyncMaster:
            def __init__(self, event):
                self.event = event

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.event.set()

        class AsyncSlave:
            def __init__(self, event):
                self.event = event

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                await self.event.wait()

        event = asyncio.Event()
        master = AsyncMaster(event)
        slave = AsyncSlave(event)

        stack = AsyncExitStack()
        await stack.enter_context(master)
        await stack.enter_context(slave)

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(stack.close(), timeout=0.1)

    @with_timeout()
    async def test_cancel_deadlock(self):
        class AsyncContext:
            def __init__(self, enter_queue, exit_queue):
                self.enter_queue = enter_queue
                self.exit_queue = exit_queue

            async def __aenter__(self):
                self.enter_queue.append(self)
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                self.exit_queue.append(self)

        event = asyncio.Event()
        enter_queue = []
        exit_queue = []

        master = AsyncContext(enter_queue, exit_queue)
        slave = AsyncContext(enter_queue, exit_queue)

        async def task(master, slave):
            async with AsyncExitStack() as stack:
                await stack.enter_context(master)
                await stack.enter_context(slave)
                await event.wait()

        task = asyncio.ensure_future(task(master, slave))
        await asyncio.sleep(1.0 / 4)
        task.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertListEqual(enter_queue, [master, slave])
        self.assertListEqual(exit_queue, [slave, master])

    @fail_on(unused_loop=False)
    @with_timeout
    async def test_exception(self):
        with self.assertRaises(asyncio.CancelledError):
            async with AsyncExitStack():
                raise asyncio.CancelledError()

        with self.assertRaises(RuntimeError):
            async with AsyncExitStack():
                raise RuntimeError()
