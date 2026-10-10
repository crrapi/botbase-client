# botbase-client

A Python library and CLI for [sys-botbase](https://github.com/olliz0r/sys-botbase), the Nintendo
Switch sysmodule that lets a computer press buttons, touch the screen, type, take screenshots, and
read and write game memory over Wi-Fi.

It covers all 50 sys-botbase commands, fixes the protocol's rough edges on the client side, and
documents what tested hardware actually does. Python 3.9+, no dependencies.

```console
$ botbase discover
192.168.1.50    sys-botbase 2.6
$ export BOTBASE_HOST=192.168.1.50
$ botbase info
version        2.6
charge         100
language       American English
title_id       01006A800016E000
build_id       21450c647b8c5940
...
$ botbase screenshot -o now.jpg
$ botbase click HOME
$ botbase type "Hello, world!" --enter
$ botbase peek 0x8 4 --region main --as hex
```

## Why use this instead of a raw socket

- **Commands finish before the call returns.** sys-botbase sends no reply for write commands.
  The client follows each one with a `getVersion` fence, so `click("A")` returns after the press.
- **Typos are caught.** sys-botbase presses A for any button name it does not know. The client
  refuses unknown names.
- **Busy debuggers are detected.** When the cheat engine holds the game (SaltyNX forces this for
  any game with a cheats folder), reads quietly return garbage. The client raises `DebuggerBusy`
  with the reason and the fix.
- **`clickSeq` noise is handled.** Its asynchronous `done` lines never leak into other replies.
- **A deterministic sequence runner** avoids an upstream `strtok` bug that can turn button names
  in `clickSeq` into A.
- **Real typing.** `type_text()` maps a US layout and sends capitals as Shift chords, because the
  system keyboard ignores the Shift modifier.
- **VPN-proof.** `--interface en0` pins the socket to the physical NIC when a tunnel routes the
  same subnet.
- **Discovery.** Scans the local /24 and confirms each host by protocol, not just an open port.

## Install

```sh
pip install git+https://github.com/crrapi/botbase-client
# or, from a clone
pip install -e .
```

The console needs Atmosphere and sys-botbase. On HOS 21 and later, read
[docs/server-setup.md](docs/server-setup.md) first: the official v2.5 can crash the console at
boot (2001-0132), and that page has the fix.

## CLI

The console address comes from `--host`, then `$BOTBASE_HOST`, then a scan of the local /24.
`--interface` (or `$BOTBASE_INTERFACE`) binds to one network interface. `--fast` drops the
per-command latency from about 50 ms to about 25 ms.

| Task | Command |
|---|---|
| Find consoles | `botbase discover [--subnet 10.0.0.0/24]` |
| Status and running game | `botbase info [--json]` |
| Screenshot | `botbase screenshot [-o file.jpg]` |
| Buttons | `botbase click A B --gap 200`, `press ZR`, `release ZR`, `hold A 1500` |
| Sticks | `botbase stick left 0 32767 --ms 400` |
| Input sequence | `botbase seq A W500 DDOWN W200 +L %0,32767 W300 -L` (add `--server` for clickSeq) |
| Touch | `botbase touch 640 360`, `touch-hold 100 600 1000`, `touch-draw 100 100 600 100` |
| Keyboard | `botbase type "text" [--enter]`, `key Return`, `key-multi LeftShift A` |
| Read memory | `botbase peek 0x40000 64 [--region heap/main/absolute] [--as dump/hex/u32/f32]` |
| Write memory | `botbase poke 0x40000 99 --as u32 --verify` |
| Pointer chain | `botbase pointer 0x1c50c00 0x10 --final 0x8 --peek 4 --as u32` |
| Freeze a value | `botbase freeze 0x40000 0x63`, `unfreeze 0x40000`, `freezes count/clear/pause/unpause` |
| Game metadata | `botbase game name`, `game icon -o icon.jpg` |
| Is it running? | `botbase running 0x010000000000100D` (exit code 0 or 1) |
| Screen | `botbase screen off`, `screen on` |
| Settings | `botbase config mainLoopSleepTime 0`, `controller joycon-right` |
| HOME menu | `botbase home`, `botbase close` |
| Anything else | `botbase raw "getTitleVersion"`, or `botbase shell` for a prompt |

## Library

```python
from botbase import Botbase, DebuggerBusy

with Botbase("192.168.1.50", interface="en0") as bb:
    bb.click("HOME")
    bb.sequence(["DRIGHT", 200, "DRIGHT", 200, "A"])   # 200 = wait 200 ms
    bb.touch([(640, 360)])
    bb.type_text("Player 1")
    open("screen.jpg", "wb").write(bb.screenshot())

    print(bb.info())                    # version, battery, title, build ID, memory access
    try:
        bb.require_memory_access()
        hp = bb.read_int(0x40100, 4)
        bb.write_int(0x40100, 999, 4)
        coins = bb.pointer_peek(4, [0x1c50c00, 0x10], final=0x8)
    except DebuggerBusy as e:
        print(e)                        # explains the cheat-engine conflict and the fix
    bb.detach_controller()
```

Every method is documented in its docstring. [docs/commands.md](docs/commands.md) maps each wire
command to its method and CLI form, with hardware test status.

## Read before you use it

- **Port 6000 has no authentication.** Anyone who reaches it can control the console and edit
  game memory. Keep it on a trusted LAN.
- **Writes are immediate.** Buttons press a real console; pokes change a running game. Memory
  writes in an online game are a ban risk.
- **Settings are global** and last until reboot (`configure` affects every client).
- [docs/quirks.md](docs/quirks.md) lists every trap found while testing: the cheat-engine
  conflict, controller screens that ignore a Pro Controller, the unmapped start of the heap,
  keyboard Shift, and more.

## Tests

```sh
python -m unittest discover -s tests
```

The tests run against `tests/fake_server.py`, which mimics sys-botbase's replies, silences,
`done` lines and failure modes. Hardware testing used an Erista Switch on HOS 22.5.0 with
Atmosphere 1.12.0 and sys-botbase 2.6 (upstream plus PR #111).

## Credits

[olliz0r/sys-botbase](https://github.com/olliz0r/sys-botbase) and its contributors; the HOS 22
memory fix is [PR #111](https://github.com/olliz0r/sys-botbase/pull/111) by quinnfrost.
