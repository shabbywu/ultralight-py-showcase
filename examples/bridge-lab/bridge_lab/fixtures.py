"""Sources served from actual registered implementations, never illustrative copies."""
import inspect
from . import bridge
from .models import Counter


def python_sources():
    return [inspect.getsource(obj) for obj in
            (bridge.add, bridge.delayed_double, Counter, Counter,
             bridge.divide, bridge.get_profile)]
