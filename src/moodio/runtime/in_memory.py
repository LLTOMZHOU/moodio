from __future__ import annotations

from moodio.runtime.service import RuntimeService


class InMemoryRuntime(RuntimeService):
    """Backward-compatible runtime alias while the service owns orchestration."""
