import asyncio
import pytest
from bridge_lab.models import Counter
from bridge_lab.bridge import add, delayed_double, divide, get_profile


def test_counter_live_history():
    counter = Counter()
    history = counter.history
    assert counter.increment(2) == 2
    assert history == [2]
    assert counter.reset() == 0
    assert history is counter.history and history == []
    with pytest.raises(TypeError):
        counter.increment('2')


@pytest.mark.parametrize('n,ms', [(21,0),(21,150),(0,0)])
def test_async(n, ms):
    assert asyncio.run(delayed_double(n,ms)) == n*2


@pytest.mark.parametrize('n,ms,exception', [(21,-1,ValueError),(21,2001,ValueError),(21,True,TypeError),('21',0,TypeError)])
def test_async_validation(n,ms,exception):
    with pytest.raises(exception):
        asyncio.run(delayed_double(n,ms))


def test_functions():
    assert add(20,22) == 42 and add(30,22) == 52
    with pytest.raises(TypeError):
        add(True,22)
    with pytest.raises(ZeroDivisionError):
        divide(1,0)
    assert get_profile() == {'name':'Bridge Lab','version':'1.0','tags':['python','js']}
