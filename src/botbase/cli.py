"""Command-line interface: `botbase <command> ...` (or `python -m botbase`).

The console address comes from --host, then $BOTBASE_HOST, then a scan of the local /24.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shlex
import struct
import sys
import time
from typing import List, Optional

from . import __version__
from .client import Botbase, BotbaseError, normalize_button
from .constants import CONFIG_KEYS, CONTROLLER_TYPES, DEFAULT_PORT, KEYS, REPLY_COMMANDS
from .discovery import default_subnet, discover

FORMATS = {"u8": "<B", "i8": "<b", "u16": "<H", "i16": "<h", "u32": "<I", "i32": "<i",
           "u64": "<Q", "i64": "<q", "f32": "<f", "f64": "<d"}


def num(text: str) -> int:
    """Parse 0x-hex, 0b-binary or decimal; negative values allowed."""
    return int(text, 0)


def hexbytes(text: str) -> bytes:
    text = text[2:] if text.lower().startswith("0x") else text
    if len(text) % 2:
        text = "0" + text
    return bytes.fromhex(text)


def resolve_host(args) -> str:
    if args.host:
        return args.host
    subnet = args.subnet or default_subnet(args.interface)
    print(f"no --host or $BOTBASE_HOST; scanning {subnet} ...", file=sys.stderr)
    found = discover(subnet, args.port, args.interface)
    if len(found) != 1:
        raise SystemExit(f"found {len(found)} sys-botbase hosts {found}; pass --host")
    print(f"using {found[0][0]} (sys-botbase {found[0][1]})", file=sys.stderr)
    return found[0][0]


def connect(args) -> Botbase:
    bb = Botbase(resolve_host(args), args.port, interface=args.interface, timeout=args.timeout)
    if args.fast:
        bb.fast_mode()
    return bb


def parse_seq(tokens: List[str]):
    """clickSeq-style tokens -> sequence() steps: A | W250 | +A | -A | %x,y | &x,y."""
    steps = []
    for tok in ",".join(tokens).split(","):
        if not tok:
            continue
        if steps and isinstance(steps[-1], tuple) and steps[-1][0] == "stick" and steps[-1][3] is None:
            steps[-1] = steps[-1][:3] + (num(tok),)  # the y of "%x,y" (may be negative)
        elif tok[0] in "Ww" and tok[1:].isdigit():
            steps.append(int(tok[1:]))
        elif tok[0] in "+-":
            steps.append(("press" if tok[0] == "+" else "release", normalize_button(tok[1:])))
        elif tok[0] in "%&":
            steps.append(("stick", "left" if tok[0] == "%" else "right", num(tok[1:]), None))
        else:
            steps.append(normalize_button(tok))
    for s in steps:
        if isinstance(s, tuple) and s[0] == "stick" and s[3] is None:
            raise SystemExit("a stick step needs x,y")
    return steps


def show_bytes(data: bytes, fmt: str, base: int = 0) -> str:
    if fmt == "hex":
        return data.hex().upper()
    if fmt == "dump":
        rows = []
        for i in range(0, len(data), 16):
            chunk = data[i:i + 16]
            text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            rows.append(f"{base + i:012x}  {chunk.hex(' '):<47}  {text}")
        return "\n".join(rows)
    return str(struct.unpack(FORMATS[fmt], data[:struct.calcsize(FORMATS[fmt])])[0])


def encode_value(value: str, fmt: str) -> bytes:
    if fmt == "hex":
        return hexbytes(value)
    if fmt.startswith("f"):
        return struct.pack(FORMATS[fmt], float(value))
    return struct.pack(FORMATS[fmt], num(value))


def run(args) -> int:
    c = args.cmd
    if c == "discover":
        subnet = args.subnet or default_subnet(args.interface)
        found = discover(subnet, args.port, args.interface)
        for host, ver in found:
            print(f"{host}\tsys-botbase {ver}")
        if not found:
            print(f"no sys-botbase on {subnet}", file=sys.stderr)
            return 1
        return 0

    bb = connect(args)
    try:
        if c == "info":
            data = bb.info()
            if args.json:
                print(json.dumps(data, indent=1))
            else:
                for k, v in data.items():
                    if k in ("main_nso_base", "heap_base") and v is not None:
                        v = f"{v:#x}"
                    print(f"{k:14} {'' if v is None else v}")
        elif c == "screenshot":
            path = args.output or datetime.datetime.now().strftime("switch-%Y%m%d-%H%M%S.jpg")
            print(bb.save_screenshot(path))
        elif c == "click":
            for i, b in enumerate(args.buttons):
                if i and args.gap:
                    time.sleep(args.gap / 1000)
                bb.click(b)
        elif c == "press":
            bb.press(args.button)
        elif c == "release":
            bb.release(args.button)
        elif c == "hold":
            bb.hold(args.button, args.ms)
        elif c == "stick":
            if args.ms:
                bb.tilt(args.side, args.x, args.y, args.ms)
            else:
                bb.set_stick(args.side, args.x, args.y)
        elif c == "seq":
            steps = parse_seq(args.steps)
            if args.server:
                bb.click_seq(steps)
            else:
                bb.sequence(steps)
        elif c == "cancel":
            bb.click_cancel()
            bb.touch_cancel()
        elif c == "touch":
            pts = list(zip(args.coords[::2], args.coords[1::2]))
            if len(args.coords) % 2:
                raise SystemExit("touch needs x y pairs")
            bb.touch(pts)
        elif c == "touch-hold":
            bb.touch_hold(args.x, args.y, args.ms)
        elif c == "touch-draw":
            if len(args.coords) % 2 or len(args.coords) < 4:
                raise SystemExit("touch-draw needs at least two x y pairs")
            bb.touch_draw(list(zip(args.coords[::2], args.coords[1::2])))
        elif c == "type":
            bb.type_text(args.text + ("\n" if args.enter else ""))
        elif c == "key":
            bb.key(*args.keys)
        elif c == "key-multi":
            bb.key_multi(*args.keys)
        elif c == "key-mod":
            pairs = []
            for p in args.pairs:
                k, _, m = p.partition(":")
                pairs.append((k, int(m) if m.isdigit() else m))
            bb.key_mod(pairs)
        elif c == "peek":
            data = bb.peek(args.offset, args.size, args.region)
            print(show_bytes(data, args.fmt, args.offset))
        elif c == "poke":
            bb.poke(args.offset, encode_value(args.value, args.fmt), args.region)
            if args.verify:
                n = len(encode_value(args.value, args.fmt))
                got = bb.peek(args.offset, n, args.region)
                print("verified" if got == encode_value(args.value, args.fmt) else f"MISMATCH: {got.hex()}")
        elif c == "pointer":
            chain = args.chain
            if args.peek:
                print(show_bytes(bb.pointer_peek(args.peek, chain, args.final), args.fmt))
            elif args.poke:
                bb.pointer_poke(hexbytes(args.poke), chain, args.final)
            elif args.relative:
                print(f"{bb.pointer_relative(chain, args.final):#x}")
            elif args.final:
                print(f"{bb.pointer_address(chain, args.final):#x}")
            else:
                print(f"{bb.pointer(chain):#x}")
        elif c == "freeze":
            bb.freeze(args.offset, hexbytes(args.value))
        elif c == "unfreeze":
            bb.unfreeze(args.offset)
        elif c == "freezes":
            if args.action == "count":
                print(bb.freeze_count())
            else:
                getattr(bb, f"freeze_{args.action}")()
        elif c == "game":
            if args.field == "icon":
                path = args.output or "icon.jpg"
                with open(path, "wb") as f:
                    f.write(bb.game_icon())
                print(path)
            else:
                print(bb.game_info(args.field))
        elif c == "running":
            running = bb.is_program_running(args.program_id)
            print("yes" if running else "no")
            return 0 if running else 1
        elif c == "screen":
            bb.screen_on() if args.state == "on" else bb.screen_off()
        elif c == "config":
            bb.configure(args.name, args.value)
        elif c == "controller":
            bb.set_controller_type(args.type if args.type in CONTROLLER_TYPES else int(args.type))
        elif c == "detach":
            bb.detach_controller()
        elif c == "home":
            bb.go_home()
        elif c == "close":
            print("closed" if bb.close_app() else "still running (a controller screen may be eating input)")
        elif c == "raw":
            out = bb.raw(" ".join(args.line))
            if out:
                print(out)
        elif c == "shell":
            shell(bb)
        return 0
    finally:
        bb.close()


def shell(bb: Botbase) -> None:
    """Interactive prompt: raw sys-botbase lines, plus `screenshot [path]` and `quit`."""
    print(f"connected to {bb.host}:{bb.port} (sys-botbase {bb.version()}); "
          "type raw commands, `screenshot [path]`, or `quit`")
    while True:
        try:
            line = input("botbase> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in ("quit", "exit"):
            return
        try:
            if line.split()[0] == "screenshot":
                parts = shlex.split(line)
                print(bb.save_screenshot(parts[1] if len(parts) > 1 else "screen.jpg"))
                continue
            word = line.split()[0]
            if word in ("click", "press", "release"):
                normalize_button(line.split()[1] if len(line.split()) > 1 else "")
            out = bb.raw(line)
            print(out if word in REPLY_COMMANDS else "ok")
        except (BotbaseError, ValueError, OSError) as e:
            print(f"error: {e}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="botbase", description="Control a Nintendo Switch running sys-botbase.")
    p.add_argument("--version", action="version", version=f"botbase {__version__}")
    p.add_argument("--host", default=os.environ.get("BOTBASE_HOST"), help="console IP ($BOTBASE_HOST; default: scan)")
    p.add_argument("--port", type=int, default=int(os.environ.get("BOTBASE_PORT", DEFAULT_PORT)))
    p.add_argument("--interface", default=os.environ.get("BOTBASE_INTERFACE"),
                   help="bind to this network interface, e.g. en0 when a VPN routes the LAN subnet ($BOTBASE_INTERFACE)")
    p.add_argument("--subnet", default=os.environ.get("BOTBASE_SUBNET"), help="subnet to scan (default: local /24)")
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--fast", action="store_true", help="set mainLoopSleepTime 0 first (about 25 ms per command)")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="command")

    def add(name, help_text):
        return sub.add_parser(name, help=help_text, description=help_text)

    add("discover", "scan the local network for sys-botbase")
    s = add("info", "version, battery, language, running game, build ID, memory access")
    s.add_argument("--json", action="store_true")
    s = add("screenshot", "save the current screen as JPEG")
    s.add_argument("-o", "--output")

    s = add("click", "press and release buttons: A B X Y L R ZL ZR PLUS MINUS LSTICK RSTICK DUP DDOWN DLEFT DRIGHT HOME CAPTURE PALMA UNUSED")
    s.add_argument("buttons", nargs="+")
    s.add_argument("--gap", type=int, default=150, help="ms between buttons (default 150)")
    for name in ("press", "release"):
        s = add(name, f"{name} one button")
        s.add_argument("button")
    s = add("hold", "hold a button for N ms")
    s.add_argument("button")
    s.add_argument("ms", type=int)
    s = add("stick", "set a stick (-32768..32767; y up is positive); with --ms, push then centre")
    s.add_argument("side", choices=["left", "right"])
    s.add_argument("x", type=num)
    s.add_argument("y", type=num)
    s.add_argument("--ms", type=int)
    s = add("seq", "run inputs in order: A  W250  +A  -A  %x,y (left stick)  &x,y (right stick)")
    s.add_argument("steps", nargs="+")
    s.add_argument("--server", action="store_true",
                   help="run as clickSeq inside sys-botbase (exact timing, but see the strtok bug in docs/quirks.md)")
    add("cancel", "cancel a running clickSeq and touch")

    s = add("touch", "tap points: x y [x y ...] (1280x720)")
    s.add_argument("coords", nargs="+", type=int)
    s = add("touch-hold", "hold a finger at x y for N ms")
    s.add_argument("x", type=int)
    s.add_argument("y", type=int)
    s.add_argument("ms", type=int)
    s = add("touch-draw", "drag a finger through x y x y ...")
    s.add_argument("coords", nargs="+", type=int)

    s = add("type", "type text (US layout) into the focused text field")
    s.add_argument("text")
    s.add_argument("--enter", action="store_true", help="press Return afterwards")
    s = add("key", f"type keyboard keys by name or code ({', '.join(list(KEYS)[:6])}, ..., Return, Backspace)")
    s.add_argument("keys", nargs="+")
    s = add("key-multi", "press keys together, e.g. LeftShift A")
    s.add_argument("keys", nargs="+")
    s = add("key-mod", "type key:modifier pairs, e.g. A:Shift (the system keyboard ignores Shift this way)")
    s.add_argument("pairs", nargs="+")

    for name in ("peek", "poke"):
        s = add(name, f"{'read' if name == 'peek' else 'write'} game memory")
        s.add_argument("offset", type=num)
        if name == "peek":
            s.add_argument("size", type=num)
        else:
            s.add_argument("value", help="hex bytes, or a number with --as")
            s.add_argument("--verify", action="store_true", help="read back after writing")
        s.add_argument("--region", choices=["heap", "main", "absolute"], default="heap")
        s.add_argument("--as", dest="fmt", default="dump" if name == "peek" else "hex",
                       choices=["hex", "dump", *FORMATS] if name == "peek" else ["hex", *FORMATS])
    s = add("pointer", "follow a pointer chain from main: [[main+c0]+c1]...")
    s.add_argument("chain", nargs="+", type=num)
    s.add_argument("--final", type=num, default=0, help="added after the last load")
    s.add_argument("--relative", action="store_true", help="print relative to the heap base")
    s.add_argument("--peek", type=num, metavar="SIZE", help="read SIZE bytes at the result")
    s.add_argument("--poke", metavar="HEX", help="write bytes at the result")
    s.add_argument("--as", dest="fmt", default="hex", choices=["hex", "dump", *FORMATS])
    s = add("freeze", "keep rewriting bytes at heap+offset")
    s.add_argument("offset", type=num)
    s.add_argument("value")
    s = add("unfreeze", "stop freezing heap+offset")
    s.add_argument("offset", type=num)
    s = add("freezes", "freeze list control")
    s.add_argument("action", choices=["count", "clear", "pause", "unpause"])

    s = add("game", "running game metadata")
    s.add_argument("field", choices=["name", "author", "version", "rating", "icon"])
    s.add_argument("-o", "--output", help="icon path")
    s = add("running", "is a program ID running? (exit 0 yes, 1 no)")
    s.add_argument("program_id", type=num)
    s = add("screen", "built-in screen on or off")
    s.add_argument("state", choices=["on", "off"])
    s = add("config", "sys-botbase setting: " + ", ".join(CONFIG_KEYS))
    s.add_argument("name", choices=list(CONFIG_KEYS))
    s.add_argument("value", type=num)
    s = add("controller", "virtual controller type: " + ", ".join(CONTROLLER_TYPES))
    s.add_argument("type")
    add("detach", "remove the virtual controller")
    add("home", "go to the HOME menu")
    add("close", "close the running game (HOME, X, A)")
    s = add("raw", "send one raw command line")
    s.add_argument("line", nargs="+")
    add("shell", "interactive prompt")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (BotbaseError, ValueError, OSError) as e:
        print(f"botbase: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
