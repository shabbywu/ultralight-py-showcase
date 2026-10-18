import asyncio
import sys
import pytest
from bridge_lab.playground import Playground

DEFAULT_SOURCE = "def add(a, b):\n    return a + b\n"


def test_normal_python_modules():
    with Playground() as lab:
        py = lab.run_python('''from dataclasses import dataclass
import asyncio
import math

@dataclass
class Item:
    price: float

def total(*prices, discount=0.8):
    result = sum(prices)
    return round(result * discount, 2)

async def greeting(name):
    await asyncio.sleep(0)
    return f"hello {name}"

item = Item(math.sqrt(400))
print(total(20, 30))
''')
        assert py.item.price == 20
        assert py.total(20, 30) == 40
        assert asyncio.run(py.greeting('world')) == 'hello world'
        assert lab.name in sys.modules
    assert lab.name not in sys.modules


@pytest.mark.parametrize('source, exception', [('def calculate(:', SyntaxError), ('raise RuntimeError("load failed")', RuntimeError)])
def test_failed_reload_keeps_previous_module(source, exception):
    with Playground() as lab:
        py = lab.run_python(DEFAULT_SOURCE)
        with pytest.raises(exception):
            lab.run_python(source)
        assert lab.exports is py
        assert lab.source == DEFAULT_SOURCE
        assert py.add(20, 22) == 42
        assert sys.modules[lab.name] is lab.module


def test_reload_removes_old_definitions_and_supports_empty_module():
    with Playground() as lab:
        old = lab.run_python('def square(x):\n    return x ** 2')
        assert old.square(1_000_001) == 1_000_002_000_001
        current = lab.run_python('def cube(x):\n    return x ** 3')
        assert not hasattr(current, 'square')
        assert current.cube(3) == 27
        assert not [name for name in vars(lab.run_python('')) if not name.startswith('_')]


def test_instances_and_local_file_access(tmp_path):
    with Playground() as first, Playground() as second:
        path = tmp_path/'output.txt'
        source = f'from pathlib import Path\nPath({str(path)!r}).write_text("local Python")\nvalue = 42'
        assert first.run_python(source).value == 42
        assert path.read_text() == 'local Python'
        assert not [name for name in vars(second.run_python('')) if not name.startswith('_')]


def test_exported_globals_are_live():
    with Playground() as lab:
        py = lab.run_python('count = 0\ndef increment():\n    global count\n    count += 1')
        py.increment()
        assert py.count == 1
