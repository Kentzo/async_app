"""
Config is a subclass of UserDict that allows type-checked access.

>>> class MyConfig(Config):
>>>     name: str = Option(default='foo')
>>>
>>> MyConfig().name
'foo'
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

Indirect access is not type checked and options (via direct access) will respect these values disregarding their types.
"""
from collections import ChainMap, UserDict, OrderedDict
import typing

import typeguard


class Option:
    """
    Option is a named attribute with optional default value that can be type checked.

    It should be used within a definition of a Config subclass. Its type as well as accessors are resolved against
    its owner.
    """
    def __init__(self, name: str = None, *, default=None, doc: str = None):
        """
        @param name: Name of the option. If omitted, will be set to the name of the attribute.
        @param default: Optional default value. Its type will be verified.
        @param doc: Optional docstring for the option.
        """
        super().__init__()

        if doc is not None:
            self.__doc__ = doc

        self._name = name
        self._default = default
        self._allow_empty = False
        self._owner: typing.Type['Config'] = None
        self._attr_name = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def default(self):
        """
        @raise TypeError: If default does not match Option's type.
        """
        if self._default is None and not self._allow_empty:
            raise TypeError

        return self._default

    @property
    def type(self):
        return self._owner._option_types[self._attr_name]

    def __get__(self, instance: typing.Optional['Config'], owner: typing.Type['Config']):
        if instance is not None:
            # Mapping.get cannot be used, because self.default may fail with exception even when there is a value.
            try:
                return instance.data[self.name]
            except KeyError:
                return self.default
        else:
            return self

    def __set__(self, instance: 'Config', value):
        instance.check_type(self.name, value, attr_name=self._attr_name)
        instance.data[self.name] = value

    def __delete__(self, instance: 'Config'):
        try:
            del instance.data[self.name]
        except KeyError:
            pass

    def __set_name__(self, owner: typing.Type['Config'], name: str):
        self._owner = owner
        self._attr_name = name
        self._name = self._name if self._name is not None else name


class Config(UserDict):
    _option_types: typing.Dict[str, type]
    _option_attrs: typing.Dict[str, Option]
    _option_names: typing.Dict[str, str]

    def __init__(self, *args, **kwargs):
        """
        Initial data for every option is checked against its type definition.
        """
        super().__init__(*args, **kwargs)

    @classmethod
    def check_type(cls, name: str, value, *, attr_name=None, expected_type=None):
        """
        If name is an option, ensure that value matches its type.

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
            expected_type = cls._option_types.get(attr_name, typing.Any)

        typeguard.check_type(name, value, expected_type, None)

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

        type_hints = typing.get_type_hints(cls)

        for attr_name, attr in cls.__dict__.items():
            if not isinstance(attr, Option):
                continue

            if attr_name in option_attrs and option_attrs[attr_name].name != attr.name:
                raise AttributeError(f"mismatched override: {option_attrs[attr_name].name} != {attr.name} for {attr_name}")

            if attr.name in option_names and option_names[attr.name] != attr_name:
                raise AttributeError(f"mismatched override: {option_names[attr.name]} != {attr_name} for {attr.name}")

            attr_type = type_hints.get(attr_name, typing.Any)

            if attr._default is not None:
                cls.check_type(f'{attr.name}[default]', attr._default, expected_type=attr_type)
            else:
                try:
                    cls.check_type(f'{attr.name}[default]', None, expected_type=attr_type)
                except TypeError:
                    attr._allow_empty = False
                else:
                    attr._allow_empty = True

            option_types[attr_name] = attr_type
            option_attrs[attr_name] = attr
            option_names[attr.name] = attr_name

        cls._option_types = option_types
        cls._option_attrs = option_attrs
        cls._option_names = option_names

    #{ UserDict

    def __setitem__(self, key, item):
        option = self._option_attrs.get(key)

        if option:
            option.__set__(self, item)
        else:
            super().__setitem__(key, item)

    #}


class ChainConfig(ChainMap):
    """
    Traverse maps and return first non-default value for the attribute.
    If no value is found, first allowed default is returned.
    """
    def __getattr__(self, item):
        error = f"type object '{type(self)}' has no attribute '{item}'"

        for i, mapping in enumerate(self.maps):
            try:
                option = mapping._option_attrs[item]
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
