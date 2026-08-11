"""Target environment selection.

Endpoint URLs are attached to environments by the transport layer (Phase 1);
they are vendored together with the schemas so that a schema/endpoint bump is
always a single, reviewable change.
"""

from __future__ import annotations

import enum

__all__ = ["Environment"]


class Environment(enum.Enum):
    """Which Tax Administration environment a client talks to."""

    DEMO = "demo"
    PRODUCTION = "production"
