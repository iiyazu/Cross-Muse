"""Slice C: deterministic text rendering.  See SPEC.md section 6."""
from __future__ import annotations


def format_amount(cents, currency):
    """Render signed integer cents as '<amount> <currency>' (SPEC.md 6)."""
    raise NotImplementedError


def render_report(report):
    """Render a Report as stable text (SPEC.md 6)."""
    raise NotImplementedError
