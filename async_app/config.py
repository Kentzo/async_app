"""
The Config container is a typed dict-like class to store application's config.
"""
from collections import ChainMap, UserDict, OrderedDict
import copy
from typing import Any, Callable, ClassVar, Dict, Generic, GenericMeta, Iterable, Hashable, Optional, Type, TypeVar, Union, get_type_hints

import typeguard


Self = TypeVar('Self')
OptionType = TypeVar('OptionType')


class Option(Generic[OptionType]):
    """
    Option is a named attribute with optional default value that can be type checked.

    It should be used within a definition of a Config subclass. Its type as well as accessors are resolved against
    its owner.

    >>> class C(Config):
    >>>     first_name: str = Option()
    >>>     last_name: str = Option('LastName')
    >>>     age: int = Option(default=42)
    >>>     tel: str = Option(doc="Telephone #")
    """
    def __init_subclass__(cls, **kwargs):
        super(GenericMeta, cls).__setattr__('_gorg', cls)
        super().__init_subclass__(**kwargs)

    def __init__(self, name: str = None, *, default: Union[Callable[[], OptionType], OptionType] = None, doc: str = None) -> None:
        """
        @param name: Optional name. If omitted, will be set to the name of the attribute.
        @param default: Optional default value or callable that returns default.
            It's resolved on the first access and its type is verified.
        @param doc: Optional docstring for the option.
        """
        super().__init__()

        if doc is not None:
            self.__doc__ = doc

        self._name: str = name
        self._doc: Optional[str] = doc  # check whether doc was assigned
        self._default: Union[Callable, OptionType] = default

        self._owner: Type['Config'] = None
        self._attr_name: str = None

        self._is_default_valid = None
        self._is_default_callable = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def type(self) -> Type[OptionType]:
        return self._owner._option_types[self._attr_name]

    def __get__(self: Self, instance: Optional['Config'], owner: Type['Config']) -> Union[Self, OptionType]:
        if instance is not None:
            if self.name in instance.data:
                return instance.data[self.name]
            else:
                d = self.resolve_value(instance, self.resolve_default(instance, self._default))
                instance.data[self.name] = d
                return d
        else:
            return self

    def __set__(self, instance: 'Config', value: OptionType) -> None:
        value = self.resolve_value(instance, value)
        instance.check_type(self.name, value, attr_name=self._attr_name)
        instance.data[self.name] = value

    def __delete__(self, instance: 'Config') -> None:
        try:
            del instance.data[self.name]
        except KeyError:
            pass

    def __set_name__(self, owner: Type['Config'], name: str) -> None:
        self._owner = owner
        self._attr_name = name
        self._name = self._name if self._name is not None else name

    def resolve_default(self, instance: 'Config', default: OptionType) -> OptionType:
        """
        Called before default is set.

        Subclasses can override this to provide custom default.

        >>> class DictOption(Option[Dict]):
        >>>     '''Make a copy of a default dict.'''
        >>>     def resolve_default(self, instance, default):
        >>>         if isinstance(default, dict):
        >>>             return dict(default)
        >>>         else:
        >>>             return super().resolve_default(instance, default)
        """
        if self._is_default_valid is None:
            try:
                instance.check_type(f'{self.name}[default]', self._default, attr_name=self._attr_name)
            except TypeError:
                self._is_default_valid = False
            else:
                self._is_default_valid = True

        if self._is_default_valid:
            d = self._default
        elif callable(self._default):
            d = self._default()
            instance.check_type(f'{self.name}[default]', d, attr_name=self._attr_name)
        else:
            raise TypeError(f"{self._default} is not allowed default for {self.name}")

        return d

    def resolve_value(self, instance: 'Config', value: OptionType):
        """
        Called before value is set.

        Subclasses can override to transform value.

        >>> class PathOption(Option[Path]):
        >>>     '''Transform str to Path'''
        >>>     def resolve_value(self, instance, value):
        >>>         if isinstance(value, str):
        >>>             return Path(value)
        >>>         else:
        >>>             return super().resolve_value(value)
        """
        return value

    def resolve_type(self, owner: Type['Config'], option_type):
        """
        Called before type is set.

        Subclass can override this to perform additional checks.

        >>> class FloatOption(Option[float]):
        >>>     '''Require explicit float annotation'''
        >>>     def resolve_type(self, owner, option_type):
        >>>         if not issubclass(option_type, float):
        >>>             raise RuntimeError
        >>>         else:
        >>>             return super().resolve_type(owner, option_type)
        """
        return option_type


class Config(UserDict):
    """
    Config is a subclass of UserDict that allows type-checked access.

    >>> class MyConfig(Config):
    >>>     name: str = Option(default='foo')
    >>>
    >>> MyConfig().name, MyConfig().name == MyConfig()['name']
    'foo', True
    >>> MyConfig(name='bar').name
    'bar'
    >>> c = MyConfig()
    >>> c.name = 'bar'
    >>> c.name
    'bar'
    >>> c = MyConfig()
    >>> c['name'] = 'bar'
    >>> c.name
    'bar'
    >>> c = MyConfig()
    >>> c.data['name'] = 'bar'
    >>> c.name
    'bar'
    >>> c.name = 42
    TypeError
    >>> c['name'] = 42
    TypeError
    >>> c.data['name'] = 42  # ok
    >>> c.name
    42

    Every option can either be accessed directly:
      - via the dict interface
      - by the corresponding attribute
    or indirectly via the UserDict.data attribute.

    Direct access is type checked: an attempt to set incorrect value will raise TypeError.
    Indirect access is not type checked and options will respect these values disregarding their types.

    The get_nested, set_nested and pop_nested methods allows to access nested dict-like objects:
    >>> class Contact(Config):
    >>>     tel: str = Option()
    >>>
    >>> class Employee(Config):
    >>>     contact: Contact = ConfigOption()
    >>>
    >>> e = Employee()
    >>> e.set_nested(('contact', 'tel'), '555-0199')
    >>> print(e.get_nested(('contact', 'tel')))
    '555-0199'
    >>> print(e.pop_nested(('contact', 'tel')))
    '555-0199'
    >>> print(e.get_nested(('contact', 'tel')))
    '555-0100'
    """
    data: Dict
    _option_types: ClassVar[Dict[str, type]]  # attr name -> expected attr type
    _option_attrs: ClassVar[Dict[str, Option]]  # attr name -> attr
    _option_names: ClassVar[Dict[str, str]]  # option name -> attr name

    @classmethod
    def check_type(cls, name: str, value: OptionType, *, attr_name: str = None, expected_type: Type[OptionType] = None):
        """
        If name is an option, ensure that value matches its type.

        @param name: Name of the option to check.

        @param value: Value of the option to check.

        @param attr_name: If given, it will be used instead of look up.

        @param expected_type: If given, it will be used instead of look up.

        @raise TypeError: If value mismatches type for a given name.

        @note: If name does not point to an existing option, typing.Any is implied.
        """
        if attr_name is None and expected_type is None:
            attr_name = cls._option_names.get(name)

            if attr_name is None:
                return

        if expected_type is None:
            expected_type = cls._option_types.get(attr_name, Any)

        typeguard.check_type(name, value, expected_type, None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        option_types = OrderedDict()
        option_attrs = OrderedDict()
        option_names = OrderedDict()

        try:
            option_types.update(cls._option_types)
            option_attrs.update(cls._option_attrs)
            option_names.update(cls._option_names)
        except AttributeError:
            pass

        type_hints = get_type_hints(cls)

        for attr_name, attr in cls.__dict__.items():
            if not isinstance(attr, Option):
                continue

            if attr_name in option_attrs and option_attrs[attr_name].name != attr.name:
                raise AttributeError(f"mismatched override: {option_attrs[attr_name].name} != {attr.name} for {attr_name}")

            if attr.name in option_names and option_names[attr.name] != attr_name:
                raise AttributeError(f"mismatched override: {option_names[attr.name]} != {attr_name} for {attr.name}")

            attr_type = attr.resolve_type(cls, type_hints.get(attr_name, Any))

            if attr._doc is None:
                attr.__doc__ = attr_type.__doc__

            option_types[attr_name] = attr_type
            option_attrs[attr_name] = attr
            option_names[attr.name] = attr_name

        cls._option_types = option_types
        cls._option_attrs = option_attrs
        cls._option_names = option_names

    def get_nested(self, keys: Iterable[Hashable], default=None):
        """
        Return the value for keys if each key references a nested object that implements __getitem__, else default.

        >>> c = Config({'a': {'b': {'c': 42}}})
        >>> assert c.get_nested(('a', 'b', 'c')) == 42
        >>> assert c.get_nested(('d', 'e', 'f'), 9000) == 9000
        """
        value = self

        try:
            i = -1
            for i, k in enumerate(keys):
                value = value[k]
        except KeyError:
            return default
        else:
            if i == -1:
                raise TypeError("get_nested expected at least 1 key, got 0")
            else:
                return value

    def set_nested(self, keys: Iterable[Hashable], value) -> None:
        """
        Set the value for keys where each key references a nested object that implements __getitem__.

        >>> c = Config({'a': {'b': {'c': None}}})
        >>> c.set_nested(('a', 'b', 'c'), 42)
        >>> assert c['a']['b']['c'] == 42
        """
        attr = self
        it = iter(keys)

        try:
            cur = next(it)
        except StopIteration:
            raise TypeError("set_nested expected at least 1 key, got 0")

        for nxt in it:
            attr = attr[cur]
            cur = nxt

        attr[cur] = value

    def pop_nested(self, keys: Iterable[Hashable], *args):
        """
        If each key in keys references a nested object that implemented __getitem__, remove it and return its value,
        else return default.

        >>> c = Config({'a': {'b': {'c': 42}}})
        >>> assert c.pop_nested(('a', 'b', 'c')) == 42
        >>> >>> assert c.pop_nested(('a', 'b', 'c'), 9000) == 9000
        """
        if len(args) > 1:
            raise TypeError("pop_nested expected at most 2 arguments, got 3")

        attr = self
        it = iter(keys)

        try:
            cur = next(it)
        except StopIteration:
            raise TypeError("pop_nested expected at least 1 key, got 0")

        try:
            for nxt in it:
                attr = attr[cur]
                cur = nxt

            return attr.pop(cur)
        except KeyError:
            if args:
                return args[0]
            else:
                raise

    #{ UserDict

    def __getitem__(self, key):
        option = self.__class__._option_attrs.get(key)

        if option is not None:
            return option.__get__(self, type(self))
        else:
            return super().__getitem__(key)

    def __setitem__(self, key, value):
        option = self.__class__._option_attrs.get(key)

        if option is not None:
            option.__set__(self, value)
        else:
            super().__setitem__(key, value)

    #}


ConfigOptionType = TypeVar('ConfigOptionType', bound=Config)


class ConfigOption(Option[ConfigOptionType]):
    """
    Like Option but converts value to the Config type if needed.

    >>> class Contact(Config):
    >>>     tel: str = Option(default='555-0100')
    >>>
    >>> class Employee(Config):
    >>>     contact: Contact = ConfigOption()
    >>>
    >>> print(Employee().contact.tel)
    '555-0100'

    @note: Retains a reference of assigned config, not a copy.

    @note: If default is None, new Config will be created.
        If default is an instance of config, it will be deep copied.
    """
    def resolve_default(self, instance, default):
        if default is None:
            return self.type()
        elif isinstance(default, self.type):
            return copy.deepcopy(default)
        else:
            return super().resolve_default(instance, default)

    def resolve_value(self, instance, value):
        option_type = self.type

        if not isinstance(value, option_type):
            return option_type(value)
        else:
            return super().resolve_value(instance, value)

    def resolve_type(self, owner, option_type):
        if not issubclass(option_type, Config):
            raise TypeError(f'{self.name} must have annotation of type Config')

        return super().resolve_type(owner, option_type)


class ChainConfig(ChainMap):
    """
    Traverse maps and return first non-default value for the attribute.
    If no value is found, first allowed default is returned.

    >>> class A(Config):
    >>>     first_name: str = Option
    >>>
    >>> class B(Config):
    >>>     last_name: str = Option
    >>>
    >>> c: Union[A, B] = ChainConfig(A(), B())
    >>> print(c.first_name)
    >>> print(c.last_name)
    """
    def __getattr__(self, item):
        error = f"type object '{type(self)}' has no attribute '{item}'"

        for i, mapping in enumerate(self.maps):
            try:
                option = mapping.__class__._option_attrs[item]
                break
            except KeyError:
                continue
        else:
            raise AttributeError(error)

        for mapping in self.maps[i:]:
            try:
                return mapping.data[option.name]
            except KeyError:
                continue

        for mapping in self.maps[i:]:
            try:
                return getattr(mapping, item)
            except (TypeError, AttributeError):
                continue
        else:
            raise AttributeError(error)
