"""HydraBot dynamic-tool shim → polymarket_engine package.

Imports may fail if optional deps (websockets, aiohttp, pyarrow) aren't
installed; the dynamic loader at agent.py catches the exception and skips
this file so the bot still starts.
"""

from polymarket_engine.tools import get_tools  # noqa: F401
