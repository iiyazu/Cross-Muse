__all__ = [
    "auto_merge",
    "get_changed_paths",
    "infer_review_fallback",
    "is_spawn_transient",
    "review_fallback_positive_line",
    "review_fallback_positive_reason",
    "review_fallback_positive_text",
    "review_fallback_rework_reason",
    "review_fallback_section_heading",
    "review_infra_failure_reason",
    "review_infra_reason_from_exception",
    "run_execution_god",
    "run_gate",
    "run_review_god",
    "spawn_result_transient",
]

_EXPORT_MODULES = {
    "run_execution_god": "xmuse_core.platform.execution.executor",
    "get_changed_paths": "xmuse_core.platform.execution.gate",
    "run_gate": "xmuse_core.platform.execution.gate",
    "auto_merge": "xmuse_core.platform.execution.merger",
    "infer_review_fallback": "xmuse_core.platform.execution.review",
    "is_spawn_transient": "xmuse_core.platform.execution.review",
    "review_fallback_positive_line": "xmuse_core.platform.execution.review",
    "review_fallback_positive_reason": "xmuse_core.platform.execution.review",
    "review_fallback_positive_text": "xmuse_core.platform.execution.review",
    "review_fallback_rework_reason": "xmuse_core.platform.execution.review",
    "review_fallback_section_heading": "xmuse_core.platform.execution.review",
    "review_infra_failure_reason": "xmuse_core.platform.execution.review",
    "review_infra_reason_from_exception": "xmuse_core.platform.execution.review",
    "spawn_result_transient": "xmuse_core.platform.execution.review",
    "run_review_god": "xmuse_core.platform.execution.review_god",
}


def __getattr__(name):
    if name not in _EXPORT_MODULES:
        raise AttributeError(name)
    import importlib

    module = importlib.import_module(_EXPORT_MODULES[name])
    return getattr(module, name)
