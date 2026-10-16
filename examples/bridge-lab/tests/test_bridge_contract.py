import inspect
from bridge_lab.bridge import register_api
from bridge_lab.fixtures import python_sources


class Registry:
    def __init__(self):
        self.functions = {}
        self.objects = {}

    def register(self, fn):
        self.functions[fn.__name__] = fn

    def register_object(self, name, obj, *, members):
        self.objects[name] = (obj, members)


def test_registration_and_independence():
    api, other = Registry(), Registry()
    counter = register_api(api)
    independent = register_api(other)
    assert set(api.functions) == {'add','delayed_double','divide','get_profile','reset_counter','get_status'}
    assert inspect.iscoroutinefunction(api.functions['delayed_double'])
    assert api.objects['counter'] == (counter,['value','history','increment','reset'])
    counter.increment(3)
    assert api.functions['get_status']()['counter'] == 3
    assert independent.value == 0
    assert api.functions['reset_counter']() == 0
    assert len(python_sources()) == 6
    assert 'return a + b' in python_sources()[0]
