import asyncio
from .models import Counter


def add(a: int, b: int) -> int:
    if type(a) is not int or type(b) is not int:
        raise TypeError("a and b must be ints")
    return a + b


async def delayed_double(n: int, ms: int = 150) -> int:
    if type(n) is not int or type(ms) is not int:
        raise TypeError("n and ms must be ints")
    if not 0 <= ms <= 2000:
        raise ValueError("ms must be between 0 and 2000")
    await asyncio.sleep(ms / 1000)
    return n * 2


def divide(a: float, b: float) -> float:
    return a / b


def get_profile():
    return {"name": "Bridge Lab", "version": "1.0", "tags": ["python", "js"]}


def register_api(api):
    counter = Counter()

    def reset_counter() -> int:
        return counter.reset()

    def get_status():
        return {"ready": True, "version": "0.5.0", "counter": counter.value}

    for function in (add, delayed_double, divide, get_profile, reset_counter, get_status):
        api.register(function)
    api.register_object("counter", counter,
                        members=["value", "history", "increment", "reset"])
    return counter
