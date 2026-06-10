__all__ = [
    "AgentSpawner",
    "EventBus",
    "GodConfig",
    "InvalidTransitionError",
    "LaneStateMachine",
    "McpToolHandler",
    "PlatformOrchestrator",
    "ReviewPlaneController",
    "SpawnResult",
    "StateValidationError",
]

_EXPORT_MODULES = {
    "AgentSpawner": "xmuse_core.platform.agent_spawner",
    "GodConfig": "xmuse_core.platform.agent_spawner",
    "SpawnResult": "xmuse_core.platform.agent_spawner",
    "EventBus": "xmuse_core.platform.event_bus",
    "McpToolHandler": "xmuse_core.platform.mcp_tools",
    "PlatformOrchestrator": "xmuse_core.platform.orchestrator",
    "ReviewPlaneController": "xmuse_core.platform.review_plane",
    "InvalidTransitionError": "xmuse_core.platform.state_machine",
    "LaneStateMachine": "xmuse_core.platform.state_machine",
    "StateValidationError": "xmuse_core.platform.state_validation",
}


def __getattr__(name):
    if name not in _EXPORT_MODULES:
        raise AttributeError(name)
    import importlib

    module = importlib.import_module(_EXPORT_MODULES[name])
    return getattr(module, name)
