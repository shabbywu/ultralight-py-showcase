"""Initial editor code, based on the actual baseline implementations."""
import inspect
from . import bridge
from .models import Counter


def python_sources():
    counter = inspect.getsource(Counter) + '\n\ncounter = Counter()\n'
    return [inspect.getsource(bridge.add),
            'import asyncio\n\n' + inspect.getsource(bridge.delayed_double),
            counter, counter, inspect.getsource(bridge.divide),
            inspect.getsource(bridge.get_profile)]
