import abc
import asyncio
import collections
import contextlib
import functools
import logging.handlers
import signal
import sys
import threading
from typing import Any, Awaitable, Callable, Generic, GenericMeta, Optional, Type, TypeVar
import weakref

from .config import Config

LOG = logging.getLogger(__name__)


Self = TypeVar('Self')


class Runnable(abc.ABC, collections.Awaitable):
    """
    Runnable is a convenience wrapper around asyncio.Task with distinct flow:
      - `initialize` is called only once, and is the best place to allocate task-related resources or abort execution
        entirely due to some precondition
      - `main` is where all the work happens
      - `cleanup` is called only once after main returns or raises

    Each runnable has an associated `name` (ivar) and `LOG` (cvar):
      - `name` defaults to classname and can be customized via `__init__`
      - `LOG` defaults to __module__.__qualname__ (e.g. my.app.Service) and can be customized as any other cvar

    As asyncio's Task, Runnable can either complete by return, due to exception or by being cancelled.
    Completion due to exception (including cancellation) is considered an abnormal abort.

    A concept of abortion is just a convenience to distinguish non-clean exits and otherwise identical to stop.

    >>> class Service(Runnable):
    >>>     async def initialize(self):
    >>>         # It's safe to allocate resources that require event loop here
    >>>         if not await allocate_resources():
    >>>             self.abort()
    >>>             return
    >>>
    >>>         super().initialize()
    >>>
    >>>     async def main(self):
    >>>         await do_some_work()
    >>>
    >>>     async def cleanup(self, exc_type=None, exc_val=None, exc_tb=None):
    >>>         await dealloc_resources()
    >>>
    >>> s = Service(name='MyService')
    >>> await s.start()

    @cvar LOG: For each subclass new LOG variable is automatically created unless explicitly set.
    """
    LOG: logging.Logger = LOG.getChild('Runnable')

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if 'LOG' not in cls.__dict__:
            cls.LOG = logging.getLogger('{}.{}'.format(cls.__module__, cls.__qualname__))

    def __init__(self, *, name: str = None) -> None:
        self._name = name or type(self).__name__

        self._run_f = None

        self._initialize_f = None
        self._main_f = None
        self._cleanup_f = None

        self._should_stop = False
        self._is_initialized = False
        self._is_aborted = False

    @property
    def name(self) -> str:
        """
        Name of the runnable.
        """
        return self._name

    @property
    def should_stop(self) -> bool:
        """
        Whether runnable should stop.
        """
        return self._should_stop

    @property
    def is_initialized(self) -> bool:
        """
        Whether runnable is initialized.

        Can be used to detect errors during initialization.
        """
        return self._is_initialized

    @property
    def is_aborted(self) -> bool:
        """
        Whether runnable is aborted, e.g. due to exception.
        """
        return self._is_aborted

    @property
    def is_started(self) -> bool:
        """
        Whether task is started.
        """
        return self._run_f is not None

    @property
    def is_alive(self) -> bool:
        """
        Whether task was started and still running.
        """
        return self._run_f and not self._run_f.done()

    @property
    def is_done(self) -> bool:
        """
        Whether task was started and completed its execution.
        """
        return self._run_f and self._run_f.done()

    async def initialize(self) -> None:
        """
        Convenience method that's called only once before `main`.

        Subclasses must call super(), usually at the end of the custom implementation.

        If abort or stop is called, neither main nor cleanup will be called and underlying task will finish
        as soon as possible.

        @see: abort
        """
        self.LOG.debug("\"%s\" initialized.", self.name)
        self._is_initialized = True

    @abc.abstractmethod
    async def main(self):
        """
        Subclasses must implement this method.

        @see: initialize
        @see: cleanup
        """
        pass

    async def cleanup(self, exc_type=None, exc_val=None, exc_tb=None) -> None:
        """
        Convenience method that's called only once after `main` exits.
        """
        pass

    def start(self: Self, *, loop: asyncio.AbstractEventLoop = None) -> Self:
        """
        Schedule runnable execution.

        Create and configure underlying asyncio.Task.

        @rtype: type(self)

        @raise RuntimeError: If started more than once.
        """
        if self._run_f:
            raise RuntimeError(f"\"{self.name}\" can only be started once")

        self.LOG.debug("\"%s\" started.", self.name)
        self._run_f = asyncio.ensure_future(self.run(), loop=loop)
        self._run_f.add_done_callback(self.on_run_done)

        if self.should_stop:
            self._run_f.cancel()

        return self

    async def run(self):
        self._initialize_f = asyncio.ensure_future(self.initialize())
        self._initialize_f.add_done_callback(self.on_initialize_done)
        await self._initialize_f

        if not self.is_initialized and not self.should_stop:
            raise NotImplementedError("either super or abort()/stop() must be called in overridden initialize()")
        elif self.should_stop:
            return

        try:
            self._main_f = asyncio.ensure_future(self.main())
            self._main_f.add_done_callback(self.on_main_done)
            result = await self._main_f
        except:
            self._cleanup_f = asyncio.ensure_future(self.cleanup(*sys.exc_info()))
            self._cleanup_f.add_done_callback(self.on_cleanup_done)
            await self._cleanup_f
            raise
        else:
            self._cleanup_f = asyncio.ensure_future(self.cleanup())
            self._cleanup_f.add_done_callback(self.on_cleanup_done)
            await self._cleanup_f
            return result

    def stop(self) -> None:
        """
        Stop runnable by cancelling wrapped task.
        """
        self.LOG.debug("\"%s\" stopped.", self.name)

        if not self._should_stop:
            self._should_stop = True

            if self._run_f:
                self._run_f.cancel()

    def abort(self) -> None:
        """
        Same as stop, but sets the abort flag.

        @see: stop
        """
        self.LOG.debug("\"%s\" aborted.", self.name)
        self._is_aborted = True
        self.stop()

    def on_run_done(self, f: asyncio.Task) -> None:
        """
        Called when the run task is done.
        """
        assert f == self._run_f

        if self._run_f.cancelled():
            if not self._should_stop:
                self.LOG.debug("\"%s\" was manually cancelled.")
        elif self._run_f.exception() is not None:
            self.LOG.debug("\"%s\" failed.")
            self._is_aborted = True
        else:
            self.LOG.debug("\"%s\" succeed.")

        self._should_stop = True

    def on_initialize_done(self, f: asyncio.Task) -> None:
        """
        Called when the initialize task is done.
        """
        assert f == self._initialize_f

    def on_main_done(self, f: asyncio.Task) -> None:
        """
        Called when the main task is done.
        """
        assert f == self._main_f

    def on_cleanup_done(self, f: asyncio.Task) -> None:
        """
        Called when the cleanup task is done.
        """
        assert f == self._cleanup_f

    async def __aenter__(self):
        return self.start()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.stop()

        with contextlib.suppress(asyncio.CancelledError):
            await self

    def __await__(self):
        if self._run_f:
            return self._run_f.__await__()
        else:
            raise RuntimeError(f"\"{self.name}\" is not running")

    def __repr__(self):
        return '<{}(name={})>'.format(type(self).__name__, self.name)

    def __del__(self):
        if getattr(self, '_run_f', None) and not self._run_f.done():
            self.LOG.error("\"%s\" is destroyed with pending task.", self.name)


AppType = TypeVar('AppType', bound='App')
ConfigType = TypeVar('ConfigType', bound=Config)
ServiceType = TypeVar('ServiceType', bound='Service')


class AppLocal(threading.local):
    map = None

    def __init__(self):
        self.map = weakref.WeakValueDictionary()


class App(Runnable, Generic[ConfigType]):
    """
    App is the root runnable for the application.

    It's semantics is alike Thread: user can either subclass it and override main
    or provide a callable that returns a coroutine.

    App handles the SIGINT and SIGTERM signals by stopping itself.

    >>> class MyApp(App):
    >>>     async def main(self):
    >>>         a_service = ...
    >>>         b_service = ...
    >>>         await asyncio.gather(a_service, b_service)
    >>>
    >>> MyApp().exec()

    App provides a factory method to create services: make_service
    Subclasses of App (and Service) can override how service is created with the make_service decorator.

    @see: make_service
    """
    app_local = AppLocal()

    @classmethod
    def current_app(cls: Type[AppType], loop: asyncio.AbstractEventLoop = None) -> Optional[AppType]:
        # TODO: Use PEP 550.
        apps_map = cls.app_local.map

        try:
            loop = loop or asyncio.get_event_loop()
            loop_ref = weakref.ref(loop)
        except RuntimeError:
            LOG.warning("There is no current asyncio event loop.")
            return None

        app = apps_map.get(loop_ref)

        if app is None:
            LOG.debug("There is no active App in event loop %s.", loop)

        return app

    def __init_subclass__(cls, **kwargs):
        super(GenericMeta, cls).__setattr__('_gorg', cls)
        super().__init_subclass__(**kwargs)

    def __init__(self, target: Callable[[], Awaitable] = None, *, config: ConfigType = None, name: str = None) -> None:
        """
        @param target: Coroutine that will be awaited. If None, main must be overridden.
        """
        super().__init__(name=name)
        self._target = target
        self._config = config

    @property
    def config(self) -> Optional[ConfigType]:
        return self._config

    def exec(self, *, loop: asyncio.AbstractEventLoop = None) -> None:
        loop = loop or asyncio.get_event_loop()

        apps_map = self.app_local.map
        loop_ref = weakref.ref(loop, lambda ref: self.app_local.map.pop(ref, None))
        apps_map[loop_ref] = self

        try:
            t = self.start(loop=loop)
            loop.run_until_complete(t)
        except asyncio.CancelledError:
            pass
        finally:
            del apps_map[loop_ref]

    #{ Runnable

    async def initialize(self):
        await super().initialize()

        loop = asyncio.get_event_loop()

        try:
            loop.add_signal_handler(signal.SIGINT, self.stop)
            loop.add_signal_handler(signal.SIGTERM, self.stop)
        except NotImplementedError:
            self.LOG.debug("%s does not implement add_signal_handler", loop)

    async def main(self):
        if self._target:
            await asyncio.ensure_future(self._target())
        else:
            raise NotImplementedError("either pass \"target\" or override main")

    #}


AppType = TypeVar('AppType', bound=App)


class Service(Runnable, Generic[AppType, ConfigType]):
    """
    Service implements asynchronous task for the app.

    Almost like vanilla Runnable with attributes to access app, config and factory method for services.
    """
    def __init_subclass__(cls, **kwargs):
        super(GenericMeta, cls).__setattr__('_gorg', cls)
        super().__init_subclass__(**kwargs)

    def __init__(self, *, app: AppType = None, config: ConfigType = None, name: str = None) -> None:
        """
        @param app: App that owns the service. If None, will be resolved at the beginning of the service's execution.
        """
        super().__init__(name=name)
        self._app = app
        self._config = config

    @property
    def app(self) -> Optional[AppType]:
        return self._app

    @property
    def config(self) -> Optional[ConfigType]:
        return self._config or self.app.config

    #{ Runnable

    async def run(self, *args, **kwargs):
        current_app = App.current_app()

        if self._app is None:
            self._app = current_app
        elif self._app != current_app:
            raise RuntimeError(f"{self.name} should run in {self._app.name} but runs in {current_app.name} instead")

        return await super().run(*args, **kwargs)
