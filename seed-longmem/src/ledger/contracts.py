"""Settlement flags for orders."""

SETTLED: set[str] = set()


def mark_settled(order_id: str) -> None:
    """Record an order as settled."""
    SETTLED.add(order_id)


def is_settled(order_id: str) -> bool:
    """Whether an order is settled."""
    return order_id in SETTLED
