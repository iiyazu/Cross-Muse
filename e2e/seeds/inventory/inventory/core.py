class InventoryError(ValueError):
    pass


class Inventory:
    """See SPEC.md. reserve/release/commit are not implemented yet, and remove() has a bug."""

    def __init__(self):
        self._stock = {}

    def add(self, sku, qty):
        self._stock[sku] = self._stock.get(sku, 0) + qty

    def remove(self, sku, qty):
        self._stock[sku] = self._stock.get(sku, 0) - qty

    def stock(self, sku):
        return self._stock.get(sku, 0)
