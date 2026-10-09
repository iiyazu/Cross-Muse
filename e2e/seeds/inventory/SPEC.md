# Inventory

`Inventory` tracks stock per SKU (a non-empty string) and reservations against it.

- `add(sku, qty)`: increase stock. `qty` must be an int ≥ 1 (bools are not ints here).
- `remove(sku, qty)`: decrease stock. Fails if it would drop stock below what is reserved.
- `reserve(sku, qty) -> str`: reserve `qty` units of available stock (stock − reserved) and return a
  new reservation id (unique per inventory). Fails if not enough is available.
- `release(rid)`: cancel a reservation; the units become available again.
- `commit(rid)`: the reserved units leave the inventory: stock and reserved both drop by the
  reservation's qty; the reservation is gone.
- `available(sku) -> int`, `stock(sku) -> int`: 0 for unknown SKUs.
- Failures raise `InventoryError` (a `ValueError` subclass) and leave the inventory unchanged:
  bad qty, unknown SKU on remove/reserve, unknown or already released/committed reservation id,
  not enough stock/availability.
