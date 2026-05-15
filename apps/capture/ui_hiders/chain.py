"""Build UI hider fallback chains from configuration."""

import logging
from typing import Optional

from ui_hiders.base import UIHider
from ui_hiders.console_hider import ConsoleUIHider
from ui_hiders.renderdoc_hider import RenderDocUIHider
from ui_hiders.noop_hider import NoopUIHider

logger = logging.getLogger(__name__)


def build_ui_hider_chain(
    engine: Optional[str] = None,
    console_host: str = "127.0.0.1",
    console_port: int = 9998,
    use_renderdoc: bool = True,
) -> UIHider:
    """Build a UI hider chain with automatic fallback.

    Priority order:
      1. Console commands (if engine is specified and console is reachable)
      2. RenderDoc pass filtering (if RenderDoc grabber is in use)
      3. Noop (always succeeds, marks frames as ui_present)

    Args:
        engine: Game engine type ("ue5" or "unity"), None to skip console.
        console_host: Host for console TCP connection.
        console_port: Port for console TCP connection.
        use_renderdoc: Whether RenderDoc grabber is active.

    Returns:
        Head of the UIHider fallback chain.
    """
    chain_parts = []

    if engine in ("ue5", "unity"):
        chain_parts.append(
            ConsoleUIHider(
                engine=engine,
                host=console_host,
                port=console_port,
            )
        )

    if use_renderdoc:
        chain_parts.append(RenderDocUIHider())

    # Noop is always the final fallback
    chain_parts.append(NoopUIHider())

    # Link the chain
    head = chain_parts[0]
    current = head
    for part in chain_parts[1:]:
        current.set_fallback(part)
        current = part

    names = [p.name() for p in chain_parts]
    logger.info(f"UI hider chain: {' → '.join(names)}")
    logger.debug(f"[UI_CHAIN] engine={engine}, console={console_host}:{console_port}, "
                 f"renderdoc={use_renderdoc}, chain_length={len(chain_parts)}")

    return head
