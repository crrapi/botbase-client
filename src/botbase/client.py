"""TCP client for sys-botbase.

sys-botbase reads newline-terminated text commands on port 6000. Read commands answer with
exactly one line; write commands answer with nothing. This client hides that asymmetry: after a
silent command it sends `getVersion` as a fence and waits for the reply, so every method returns
only after sys-botbase has processed the command. Touch, keyboard and clickSeq commands are the
exception: sys-botbase hands them to worker threads, so the fence only proves they were queued.
Their methods take `wait=True` to sleep for the expected duration.
"""
from __future__ import annotations

import re
import socket
import struct
import sys
import time
from typing import Iterable, List, Optional, Sequence, Tuple, Union

from .constants import (
    ALL_COMMANDS, BUTTON_ALIASES, BUTTONS, CONFIG_KEYS, CONTROLLER_TYPES, DEFAULT_PORT, KEYS,
    LANGUAGES, MAX_LINE_LENGTH, MODIFIER_BITS, REPLY_COMMANDS, SCREEN_HEIGHT, SCREEN_WIDTH,
    STICK_MAX, STICK_MIN, US_LAYOUT,
)

Region = str  # "heap", "main" or "absolute"
KeyLike = Union[int, str]

# A heap base below this is not a real address. sys-botbase prints whatever svcGetInfo left in
# its output variable when the debug attach failed; on HOS 22 that is 0x4.
_MIN_VALID_HEAP = 0x100000
_GAME_ERROR = re.compile(r"^nsGetApplicationControlData\(\) failed: (0x[0-9a-fA-F]+)$")


class BotbaseError(Exception):
    """Base class for errors raised by this client."""


class NoGameRunning(BotbaseError):
    """The command needs a running application and none is in the foreground."""


class DebuggerBusy(BotbaseError):
    """sys-botbase could not attach to the game because another debugger holds it.

    Atmosphere's cheat engine (dmnt) is the usual holder. SaltyNX forces dmnt to attach to
    every game that has a non-empty atmosphere/contents/<title id>/cheats folder, even when no
    cheat matches the build and even when L is held at launch. Remove or rename that folder,
    or disable SaltyNX, to give sys-botbase the debugger.
    """


class MemoryAccessError(BotbaseError):
    """A memory read failed: the address is not mapped, or no game is running."""


def _bind_to_interface(sock: socket.socket, interface: str) -> None:
    """Pin a socket to one network interface, so a VPN that routes the same subnet is bypassed."""
    if sys.platform == "darwin":
        IP_BOUND_IF = 25
        sock.setsockopt(socket.IPPROTO_IP, IP_BOUND_IF, socket.if_nametoindex(interface))
    elif sys.platform.startswith("linux"):
        SO_BINDTODEVICE = getattr(socket, "SO_BINDTODEVICE", 25)
        sock.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, interface.encode() + b"\0")
    else:
        raise BotbaseError(f"interface binding is not supported on {sys.platform}")


def _hexint(value: int) -> str:
    """Format an int the way sys-botbase's parsers want it: 0x-prefixed hex, sign in front."""
    return f"-{-value:#x}" if value < 0 else f"{value:#x}"


def _hexdata(data: bytes) -> str:
    if not data:
        raise ValueError("data must not be empty")
    return "0x" + data.hex()


def normalize_button(name: str) -> str:
    """Return the sys-botbase spelling of a button name, or raise ValueError.

    sys-botbase presses A for any name it does not recognise, so this check matters.
    """
    upper = name.strip().upper()
    upper = BUTTON_ALIASES.get(upper, upper)
    if upper not in BUTTONS:
        raise ValueError(f"unknown button {name!r} (sys-botbase would press A); "
                         f"valid: {', '.join(sorted(BUTTONS))}")
    return upper


def key_code(key: KeyLike) -> int:
    """Turn a HidKeyboardKey name ("Return", "A", "F5") or number into its code."""
    if isinstance(key, int):
        code = key
    elif key.isdigit():
        code = int(key)
    else:
        lookup = {k.lower(): v for k, v in KEYS.items()}
        if key.lower() not in lookup:
            raise ValueError(f"unknown keyboard key {key!r}")
        code = lookup[key.lower()]
    if not 4 <= code <= 231:
        raise ValueError(f"key code {code} outside 4..231 (sys-botbase ignores it)")
    return code


def _clamp_stick(value: int) -> int:
    return max(STICK_MIN, min(STICK_MAX, int(value)))


class Botbase:
    """One connection to sys-botbase.

    >>> with Botbase("192.168.1.50") as bb:
    ...     bb.click("A")
    ...     open("screen.jpg", "wb").write(bb.screenshot())
    """

    def __init__(self, host: str, port: int = DEFAULT_PORT, *, interface: Optional[str] = None,
                 timeout: float = 10.0):
        self.host, self.port, self.interface, self.timeout = host, port, interface, timeout
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if interface:
            _bind_to_interface(self._sock, interface)
        self._sock.settimeout(timeout)
        self._sock.connect((host, port))
        self._buf = b""
        # Finished clickSeq runs print "done" into the reply stream at any time.
        self.click_seq_done = 0
        # Client-side copy of the timing settings, for the wait=True estimates.
        self._config = {"buttonClickSleepTime": 50, "keySleepTime": 25, "pollRate": 17,
                        "mainLoopSleepTime": 50}

    # ----------------------------------------------------------------------------- transport

    def close(self) -> None:
        self._sock.close()

    def __enter__(self) -> "Botbase":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def send_line(self, line: str) -> None:
        """Send one raw command line. Most callers want command() instead."""
        if "\n" in line or "\r" in line:
            raise ValueError("a command must be a single line")
        if len(line) + 1 > MAX_LINE_LENGTH:
            raise ValueError(f"command is {len(line)} chars; sys-botbase reads at most {MAX_LINE_LENGTH - 1}")
        self._sock.sendall(line.encode() + b"\r\n")

    def read_line(self, timeout: Optional[float] = None) -> str:
        """Read the next reply line. "done" lines from finished clickSeq runs are counted
        in click_seq_done and skipped."""
        self._sock.settimeout(self.timeout if timeout is None else timeout)
        while True:
            while b"\n" not in self._buf:
                chunk = self._sock.recv(1 << 16)
                if not chunk:
                    raise ConnectionError("sys-botbase closed the connection")
                self._buf += chunk
            raw, self._buf = self._buf.split(b"\n", 1)
            line = raw.decode(errors="replace").rstrip("\r")
            if line == "done":
                self.click_seq_done += 1
                continue
            return line

    def sync(self, timeout: Optional[float] = None) -> str:
        """Round-trip a getVersion. Returns once every earlier command has been processed."""
        self.send_line("getVersion")
        return self.read_line(timeout)

    def command(self, *parts: object, timeout: Optional[float] = None) -> str:
        """Send one command and return its reply line ("" for a silent command).

        Silent commands are followed by a getVersion fence, so the call returns after
        sys-botbase processed the command.
        """
        line = " ".join(str(p) for p in parts)
        word = line.split(" ", 1)[0]
        if word not in ALL_COMMANDS:
            raise ValueError(f"unknown sys-botbase command {word!r}")
        self.send_line(line)
        if word in REPLY_COMMANDS:
            return self.read_line(timeout)
        self.sync(timeout)
        return ""

    def raw(self, line: str, timeout: Optional[float] = None) -> str:
        """Send any line as typed (no validation) and return its reply, or "" if silent."""
        word = line.split(" ", 1)[0] if line else ""
        self.send_line(line)
        if word in REPLY_COMMANDS:
            return self.read_line(timeout)
        self.sync(timeout)
        return ""

    # ------------------------------------------------------------------- system information

    def version(self) -> str:
        return self.command("getVersion")

    def charge(self) -> int:
        """Battery charge in percent."""
        return int(self.command("charge"))

    def system_language(self) -> Tuple[int, str]:
        code = int(self.command("getSystemLanguage"))
        return code, LANGUAGES.get(code, f"unknown ({code})")

    def is_program_running(self, program_id: int) -> bool:
        """True if a process with this program ID runs (games and sysmodules alike)."""
        return self.command("isProgramRunning", _hexint(program_id)) == "1"

    def fd_count(self) -> int:
        """Open sockets inside sys-botbase, including its listener."""
        return int(self.command("fdCount"))

    # -------------------------------------------------------------------- running game info

    def _game_hex(self, cmd: str) -> Optional[int]:
        out = self.command(cmd)
        return int(out, 16) if out else None

    def title_id(self) -> Optional[int]:
        """Program ID of the foreground application, or None when no game runs."""
        return self._game_hex("getTitleID")

    def title_version(self) -> Optional[int]:
        """Installed version of the running game divided by 0x10000 (e.g. 31 for v2031616)."""
        return self._game_hex("getTitleVersion")

    def build_id(self) -> Optional[str]:
        """First 8 bytes of the main module's build ID, as lowercase hex. Atmosphere names
        cheat files after the upper-case form of this value."""
        return self.command("getBuildID") or None

    def main_nso_base(self) -> Optional[int]:
        return self._game_hex("getMainNsoBase")

    def heap_base(self) -> Optional[int]:
        """Start of the game's heap region (not every page in it is mapped).

        Raises DebuggerBusy when sys-botbase could not attach to the game."""
        value = self._game_hex("getHeapBase")
        if value is not None and value < _MIN_VALID_HEAP:
            raise DebuggerBusy(f"getHeapBase returned {value:#x}; another debugger holds the game. "
                               + (DebuggerBusy.__doc__ or "").split("\n\n", 1)[1].strip())
        return value

    def require_memory_access(self) -> int:
        """Return the heap base, or raise NoGameRunning / DebuggerBusy. Call this before
        heap or pointer work: a busy debugger makes reads return stale or empty data."""
        base = self.heap_base()
        if base is None:
            raise NoGameRunning("no application is running")
        return base

    def game_info(self, field: str) -> str:
        """NACP metadata of the running game: name, author, version or rating."""
        if field not in ("name", "author", "version", "rating"):
            raise ValueError("field must be name, author, version or rating")
        out = self.command("game", field)
        if _GAME_ERROR.match(out):
            raise NoGameRunning(out)
        return out

    def game_icon(self) -> bytes:
        """The running game's icon as JPEG bytes."""
        out = self.command("game", "icon", timeout=max(self.timeout, 20))
        if _GAME_ERROR.match(out):
            raise NoGameRunning(out)
        return bytes.fromhex(out)

    def info(self) -> dict:
        """Everything the read-only info commands report, in one dict."""
        lang = self.system_language()
        data = {"version": self.version(), "charge": self.charge(), "language": lang[1],
                "title_id": None, "build_id": None, "title_version": None,
                "main_nso_base": None, "heap_base": None, "name": None, "memory_access": None}
        tid = self.title_id()
        if tid is None:
            return data
        data.update(title_id=f"{tid:016X}", build_id=self.build_id(),
                    title_version=self.title_version(), main_nso_base=self.main_nso_base())
        try:
            data["heap_base"], data["memory_access"] = self.heap_base(), True
        except DebuggerBusy:
            data["memory_access"] = False
        try:
            data["name"] = self.game_info("name")
        except NoGameRunning:
            pass
        return data

    # ------------------------------------------------------------------------------- memory

    _PEEK = {"heap": "peek", "main": "peekMain", "absolute": "peekAbsolute"}
    _PEEK_MULTI = {"heap": "peekMulti", "main": "peekMainMulti", "absolute": "peekAbsoluteMulti"}
    _POKE = {"heap": "poke", "main": "pokeMain", "absolute": "pokeAbsolute"}

    @staticmethod
    def _region(table: dict, region: Region) -> str:
        if region not in table:
            raise ValueError("region must be heap, main or absolute")
        return table[region]

    def _bytes_reply(self, out: str, what: str) -> bytes:
        if not out:
            raise MemoryAccessError(f"{what} failed (no game, unmapped address, or debugger busy)")
        return bytes.fromhex(out)

    def peek(self, offset: int, size: int, region: Region = "heap") -> bytes:
        """Read `size` bytes. `offset` is relative to the heap base, the main NSO base, or an
        absolute address. Large reads are fine: sys-botbase streams them in one line."""
        cmd = self._region(self._PEEK, region)
        out = self.command(cmd, _hexint(offset), _hexint(size), timeout=max(self.timeout, size / 50000))
        return self._bytes_reply(out, cmd)

    def peek_multi(self, items: Sequence[Tuple[int, int]], region: Region = "heap") -> List[bytes]:
        """Read several (offset, size) ranges in one round trip."""
        if not items:
            return []
        cmd = self._region(self._PEEK_MULTI, region)
        args = [a for off, size in items for a in (_hexint(off), _hexint(size))]
        data = self._bytes_reply(self.command(cmd, *args), cmd)
        out, pos = [], 0
        for _, size in items:
            out.append(data[pos:pos + size])
            pos += size
        return out

    def poke(self, offset: int, data: bytes, region: Region = "heap") -> None:
        """Write bytes. Silent: sys-botbase reports no error even if the write failed, so
        read back when it matters."""
        self.command(self._region(self._POKE, region), _hexint(offset), _hexdata(data))

    def read_int(self, offset: int, size: int = 4, region: Region = "heap", signed: bool = False) -> int:
        return int.from_bytes(self.peek(offset, size, region), "little", signed=signed)

    def write_int(self, offset: int, value: int, size: int = 4, region: Region = "heap", signed: bool = False) -> None:
        self.poke(offset, value.to_bytes(size, "little", signed=signed), region)

    def read_float(self, offset: int, region: Region = "heap") -> float:
        return struct.unpack("<f", self.peek(offset, 4, region))[0]

    def write_float(self, offset: int, value: float, region: Region = "heap") -> None:
        self.poke(offset, struct.pack("<f", value), region)

    # Pointer chains: chain[0] is relative to the main NSO base; each later element is added
    # to the previously loaded pointer. `final` is added at the end without a load.

    def pointer(self, chain: Sequence[int]) -> int:
        """Follow and load every element of the chain; return the last loaded value."""
        return int(self.command("pointer", *map(_hexint, chain)), 16)

    def pointer_address(self, chain: Sequence[int], final: int = 0) -> int:
        """Absolute address of [[main+c0]+c1]...+final (pointerAll). 0 means the chain broke."""
        return int(self.command("pointerAll", *map(_hexint, chain), _hexint(final)), 16)

    def pointer_relative(self, chain: Sequence[int], final: int = 0) -> int:
        """Like pointer_address, but relative to the heap base (pointerRelative)."""
        return int(self.command("pointerRelative", *map(_hexint, chain), _hexint(final)), 16)

    def pointer_peek(self, size: int, chain: Sequence[int], final: int = 0) -> bytes:
        out = self.command("pointerPeek", _hexint(size), *map(_hexint, chain), _hexint(final))
        return self._bytes_reply(out, "pointerPeek")

    def pointer_peek_multi(self, reads: Sequence[Tuple[int, Sequence[int], int]]) -> List[bytes]:
        """Several (size, chain, final) reads in one round trip (at most 40)."""
        if not 0 < len(reads) <= 40:
            raise ValueError("pointerPeekMulti takes 1 to 40 chains")
        args: List[str] = []
        for i, (size, chain, final) in enumerate(reads):
            if i:
                args.append("*")
            args += [_hexint(size), *map(_hexint, chain), _hexint(final)]
        data = self._bytes_reply(self.command("pointerPeekMulti", *args), "pointerPeekMulti")
        out, pos = [], 0
        for size, _, _ in reads:
            out.append(data[pos:pos + size])
            pos += size
        return out

    def pointer_poke(self, data: bytes, chain: Sequence[int], final: int = 0) -> None:
        """Write to [[main+c0]+c1]...+final. Not validated by sys-botbase: a broken chain
        writes near address `final`."""
        self.command("pointerPoke", _hexdata(data), *map(_hexint, chain), _hexint(final))

    # ------------------------------------------------------------------------------- freeze

    def freeze(self, heap_offset: int, data: bytes) -> None:
        """Rewrite `data` at heap+offset every freezeRate ms while this game runs.

        The upstream docs call the address absolute; the code adds the heap base. The freeze
        thread also waits 30 s after a new game starts before it writes anything."""
        self.command("freeze", _hexint(heap_offset), _hexdata(data))

    def unfreeze(self, heap_offset: int) -> None:
        self.command("unFreeze", _hexint(heap_offset))

    def freeze_count(self) -> int:
        return int(self.command("freezeCount"), 16)

    def freeze_clear(self) -> None:
        self.command("freezeClear")

    def freeze_pause(self) -> None:
        self.command("freezePause")

    def freeze_unpause(self) -> None:
        self.command("freezeUnpause")

    # ----------------------------------------------------------------------------- controller

    def click(self, button: str) -> None:
        """Press and release a button (held for buttonClickSleepTime ms)."""
        self.command("click", normalize_button(button))

    def press(self, button: str) -> None:
        """Hold a button down until release()."""
        self.command("press", normalize_button(button))

    def release(self, button: str) -> None:
        self.command("release", normalize_button(button))

    def hold(self, button: str, ms: int) -> None:
        """Hold a button for `ms` milliseconds, then release it."""
        self.press(button)
        time.sleep(ms / 1000)
        self.release(button)

    def set_stick(self, side: str, x: int, y: int) -> None:
        """Set a stick: side "left"/"right", x and y in -0x8000..0x7FFF (y up is positive).
        The stick stays there until set again."""
        side = side.upper()
        if side not in ("LEFT", "RIGHT"):
            raise ValueError("side must be left or right")
        self.command("setStick", side, _hexint(_clamp_stick(x)), _hexint(_clamp_stick(y)))

    def tilt(self, side: str, x: int, y: int, ms: int) -> None:
        """Push a stick for `ms` milliseconds, then centre it."""
        self.set_stick(side, x, y)
        time.sleep(ms / 1000)
        self.set_stick(side, 0, 0)

    def wake(self) -> None:
        """Attach the virtual controller with an input games ignore (UNUSED). Upstream reports
        that the very first HOME after attaching can be dropped (issue #67)."""
        self.click("UNUSED")

    def detach_controller(self) -> None:
        """Remove the virtual controller. Do this when finished, so it stops holding a player slot."""
        self.command("detachController")

    def set_controller_type(self, kind: Union[str, int]) -> None:
        """Change the virtual controller (this detaches it first). Use "joycon-right" when a game's
        controller screen refuses a Pro Controller: that screen ignores every button of an
        unsupported controller, HOME included."""
        value = CONTROLLER_TYPES[kind] if isinstance(kind, str) else int(kind)
        self.configure("controllerType", value)

    def sequence(self, steps: Iterable[Union[str, int, Tuple]]) -> None:
        """Run inputs one by one from this side, which is deterministic (see click_seq).

        Steps: "A" clicks, 250 (int) waits ms, ("press", "A"), ("release", "A"),
        ("stick", "left", x, y), ("hold", "A", ms)."""
        for step in steps:
            if isinstance(step, int):
                time.sleep(step / 1000)
            elif isinstance(step, str):
                self.click(step)
            else:
                op, *args = step
                {"press": self.press, "release": self.release, "stick": self.set_stick,
                 "hold": self.hold, "click": self.click}[op](*args)

    @staticmethod
    def build_click_seq(steps: Iterable[Union[str, int, Tuple]]) -> str:
        """Build a clickSeq string from the same steps sequence() takes (no "hold")."""
        out = []
        for step in steps:
            if isinstance(step, int):
                out.append(f"W{step}")
            elif isinstance(step, str):
                out.append(normalize_button(step))
            else:
                op, *args = step
                if op == "press":
                    out.append("+" + normalize_button(args[0]))
                elif op == "release":
                    out.append("-" + normalize_button(args[0]))
                elif op == "click":
                    out.append(normalize_button(args[0]))
                elif op == "stick":
                    prefix = {"LEFT": "%", "RIGHT": "&"}[args[0].upper()]
                    out.append(f"{prefix}{_clamp_stick(args[1])},{_clamp_stick(args[2])}")
                else:
                    raise ValueError(f"clickSeq has no {op!r} step")
        return ",".join(out)

    def click_seq(self, steps: Union[str, Iterable[Union[str, int, Tuple]]], wait: bool = True,
                  timeout: float = 120) -> None:
        """Run a sequence inside sys-botbase, with exact timing between steps.

        Known upstream bug: clickSequence() passes a single char to strtok() as its delimiter
        string, so whatever bytes follow it on the stack also split tokens. Some button names
        can then break apart and fall back to A (issue #93; it changes between reboots).
        Prefer sequence() unless sub-50 ms timing matters, and check the result."""
        seq = steps if isinstance(steps, str) else self.build_click_seq(steps)
        before = self.click_seq_done
        self.command("clickSeq", seq)
        if wait:
            end = time.time() + timeout
            while self.click_seq_done == before:
                if time.time() > end:
                    raise TimeoutError("clickSeq did not finish")
                self.sync()
                time.sleep(0.1)

    def click_cancel(self) -> None:
        """Stop a running clickSeq after its current step."""
        self.command("clickCancel")

    # ---------------------------------------------------------------------------- touch

    @staticmethod
    def _check_point(x: int, y: int) -> None:
        if not (0 <= x <= SCREEN_WIDTH and 0 <= y <= SCREEN_HEIGHT):
            raise ValueError(f"touch point ({x}, {y}) is outside 0..{SCREEN_WIDTH} x 0..{SCREEN_HEIGHT}")

    def touch(self, points: Sequence[Tuple[int, int]], wait: bool = True) -> None:
        """Tap each point in turn (screen pixels, 1280x720). Works docked too."""
        for p in points:
            self._check_point(*p)
        self.command("touch", *(str(v) for p in points for v in p))
        if wait:
            time.sleep(len(points) * 2 * self._config["pollRate"] / 1000 + 0.05)

    def touch_hold(self, x: int, y: int, ms: int, wait: bool = True) -> None:
        """Hold one finger at (x, y) for `ms` (at least 15)."""
        self._check_point(x, y)
        self.command("touchHold", x, y, max(15, int(ms)))
        if wait:
            time.sleep((self._config["pollRate"] + max(15, ms)) / 1000 + 0.05)

    def touch_draw(self, points: Sequence[Tuple[int, int]], wait: bool = True) -> None:
        """Press at the first point, drag through the rest, then lift."""
        for p in points:
            self._check_point(*p)
        self.command("touchDraw", *(str(v) for p in points for v in p))
        if wait:
            time.sleep((len(points) * 2 + 1) * self._config["pollRate"] / 1000 + 0.05)

    def touch_cancel(self) -> None:
        self.command("touchCancel")

    # ------------------------------------------------------------------------------ keyboard

    def _key_wait(self, presses: int) -> float:
        return presses * (self._config["keySleepTime"] + self._config["pollRate"]) / 1000 + 0.05

    def key(self, *keys: KeyLike, wait: bool = True) -> None:
        """Type keys one after another (HidKeyboardKey names or codes)."""
        codes = [key_code(k) for k in keys]
        self.command("key", *codes)
        if wait:
            time.sleep(self._key_wait(len(codes)))

    def key_mod(self, pairs: Sequence[Tuple[KeyLike, Union[str, int]]], wait: bool = True) -> None:
        """Type (key, modifier) pairs. Modifiers are HidKeyboardModifier bit numbers or names.

        The system keyboard ignores the Shift modifier sent this way (tested on HOS 22.5);
        use key_multi("LeftShift", key) or type_text() for capitals."""
        args: List[int] = []
        for k, mod in pairs:
            bit = MODIFIER_BITS[mod] if isinstance(mod, str) else int(mod)
            args += [key_code(k), bit]
        self.command("keyMod", *args)
        if wait:
            time.sleep(self._key_wait(len(pairs)))

    def key_multi(self, *keys: KeyLike, wait: bool = True) -> None:
        """Press several keys together, as one chord."""
        self.command("keyMulti", *(key_code(k) for k in keys))
        if wait:
            time.sleep(self._key_wait(1))

    def type_text(self, text: str, wait: bool = True) -> None:
        """Type text on a US layout into whatever has keyboard focus (the system keyboard
        accepts it). Shifted characters are sent as LeftShift chords."""
        missing = sorted({c for c in text if c not in US_LAYOUT})
        if missing:
            raise ValueError(f"cannot type {missing!r} on a US keyboard layout")
        run: List[int] = []
        for ch in text:
            code, shifted = US_LAYOUT[ch]
            if shifted:
                if run:
                    self.key(*run, wait=wait)
                    run = []
                self.key_multi(KEYS["LeftShift"], code, wait=wait)
            else:
                run.append(code)
                if len(run) >= 500:
                    self.key(*run, wait=wait)
                    run = []
        if run:
            self.key(*run, wait=wait)

    # -------------------------------------------------------------------------------- screen

    def screenshot(self) -> bytes:
        """JPEG of the current frame (1280x720), as the console renders it."""
        out = self.command("pixelPeek", timeout=max(self.timeout, 30))
        data = bytes.fromhex(out) if out else b""
        if data[:3] != b"\xff\xd8\xff":
            raise BotbaseError("pixelPeek did not return a JPEG")
        return data

    def save_screenshot(self, path: str) -> str:
        with open(path, "wb") as f:
            f.write(self.screenshot())
        return path

    def screen_off(self) -> None:
        """Stop scanning out to the built-in panel and switch its backlight off."""
        self.command("screenOff")

    def screen_on(self) -> None:
        self.command("screenOn")

    # ----------------------------------------------------------------------------- settings

    def configure(self, name: str, value: Union[int, bool]) -> None:
        if name not in CONFIG_KEYS:
            raise ValueError(f"unknown setting {name!r}; valid: {', '.join(CONFIG_KEYS)}")
        self.command("configure", name, int(value))
        self._config[name] = int(value)

    def fast_mode(self) -> None:
        """Cut sys-botbase's built-in sleeps for low-latency control (upstream issue #40).
        One round trip drops from about 50 ms to about 25 ms."""
        self.configure("mainLoopSleepTime", 0)

    # --------------------------------------------------------------------------- home menu

    def go_home(self) -> None:
        self.click("HOME")
        time.sleep(1.0)

    def close_app(self, settle: float = 1.2) -> bool:
        """Close the foreground game from the HOME menu (HOME, X, A). Returns True if it closed."""
        tid = self.title_id()
        if tid is None:
            return True
        self.go_home()
        self.click("X")
        time.sleep(settle)
        self.click("A")
        time.sleep(settle * 2)
        return not self.is_program_running(tid)
