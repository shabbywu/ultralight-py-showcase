class Counter:
    def __init__(self):
        self.value = 0
        self.history = []

    def increment(self, amount: int = 1) -> int:
        if type(amount) is not int:
            raise TypeError("amount must be an int")
        self.value += amount
        self.history.append(self.value)
        return self.value

    def reset(self) -> int:
        self.value = 0
        self.history.clear()
        return self.value

    def share(self, items, options):
        items.append(7)
        options["enabled"] = True
        return items
