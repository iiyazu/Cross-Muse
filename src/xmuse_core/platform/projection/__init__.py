__all__ = [
    "AggregatedStatus",
    "aggregate_status",
    "reproject_dependents_if_needed",
]


def __getattr__(name):
    if name in __all__:
        from xmuse_core.platform.projection import dependents

        return getattr(dependents, name)
    raise AttributeError(name)
