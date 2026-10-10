"""Python client and CLI for sys-botbase, the Nintendo Switch remote-control sysmodule."""
from .client import (Botbase, BotbaseError, DebuggerBusy, MemoryAccessError, NoGameRunning,
                     key_code, normalize_button)
from .discovery import discover, probe

__version__ = "0.1.0"
__all__ = ["Botbase", "BotbaseError", "DebuggerBusy", "MemoryAccessError", "NoGameRunning",
           "discover", "probe", "key_code", "normalize_button", "__version__"]
