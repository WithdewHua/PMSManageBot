"""Thread-agnostic singleton metaclass used by scheduler assembly."""

from typing import ClassVar


class SingletonMeta(type):
    """Singleton metaclass"""

    _instances: ClassVar[dict[type, object]] = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]
