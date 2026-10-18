"""Execute editor Python modules with normal local Python semantics."""
import linecache
import sys
from types import ModuleType
import uuid
import weakref

class Exports:
    """Ordinary instances expose their attributes through ultralight-py 0.5.0."""



def _cleanup(name, filename):
    sys.modules.pop(name, None)
    linecache.cache.pop(filename, None)


class Playground:
    def __init__(self):
        self.name = '_bridge_lab_' + uuid.uuid4().hex
        self.filename = f'<{self.name}>'
        self.module = None
        self.exports = None
        self.source = ''
        self._cleanup = weakref.finalize(self, _cleanup, self.name, self.filename)

    def run_python(self, source: str):
        code = compile(source, self.filename, 'exec')
        module = ModuleType(self.name)
        module.__file__ = self.filename
        previous = sys.modules.get(self.name)
        previous_lines = linecache.cache.get(self.filename)
        sys.modules[self.name] = module
        linecache.cache[self.filename] = (len(source), None, source.splitlines(True), self.filename)
        try:
            exec(code, module.__dict__)
        except BaseException:
            if previous is None:
                sys.modules.pop(self.name, None)
            else:
                sys.modules[self.name] = previous
            if previous_lines is None:
                linecache.cache.pop(self.filename, None)
            else:
                linecache.cache[self.filename] = previous_lines
            raise
        # ModuleType attributes are not discovered by ultralight-py 0.5.0.
        # An ordinary instance gives real objects a supported bridge representation.
        exports = Exports()
        exports.__dict__ = module.__dict__
        self.module = module
        self.exports = exports
        self.source = source
        return exports

    def close(self):
        self._cleanup()
        self.module = None
        self.exports = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
