# Command reference

Every command sys-botbase 2.6 understands, with the client method and CLI form that wraps it.
"Tested" means it ran against real hardware: an Erista Switch on HOS 22.5.0, Atmosphere 1.12.0,
sys-botbase 2.6 (upstream plus PR #111), on 2026-10-09.

Numbers on the wire are decimal or `0x` hex. Data arguments are `0x`-prefixed hex bytes in memory
order. Read commands answer with one line. Write commands answer with nothing.

## Memory reads

Offsets for `peek*` are relative to the heap base, to the main NSO base, or absolute.
A failed read (unmapped page, no game, busy debugger) answers with an empty line.

| Wire command | Arguments | Reply | Client | CLI | Tested |
|---|---|---|---|---|---|
| `peek` | heap offset, size | hex | `peek(off, size)` | `peek OFF SIZE` | yes |
| `peekMulti` | (offset size)... | concatenated hex | `peek_multi([(off, size), ...])` | | yes |
| `peekMain` | main offset, size | hex | `peek(off, size, "main")` | `peek --region main` | yes |
| `peekMainMulti` | (offset size)... | hex | `peek_multi(..., "main")` | | yes |
| `peekAbsolute` | address, size | hex | `peek(addr, size, "absolute")` | `peek --region absolute` | yes |
| `peekAbsoluteMulti` | (address size)... | hex | `peek_multi(..., "absolute")` | | yes |

Large reads work in one command: sys-botbase streams them in 22 KiB chunks on one line.
A 32 KiB read was tested.

## Memory writes

| Wire command | Arguments | Client | CLI | Tested |
|---|---|---|---|---|
| `poke` | heap offset, `0x`data | `poke(off, data)` | `poke OFF HEX` | yes (same-value write) |
| `pokeMain` | main offset, `0x`data | `poke(off, data, "main")` | `poke --region main` | yes (changed and restored) |
| `pokeAbsolute` | address, `0x`data | `poke(addr, data, "absolute")` | `poke --region absolute` | yes (changed and restored) |

Writes report nothing, even on failure. Read back when it matters (`poke --verify`).
Typed helpers: `read_int`, `write_int`, `read_float`, `write_float`; CLI `--as u8|u16|u32|u64|i32|f32|...`.

## Pointer chains

A chain is `c0 c1 ... cn`: load `[main + c0]`, then `[previous + c1]`, and so on.

| Wire command | Arguments | Reply | Client | Tested |
|---|---|---|---|---|
| `pointer` | c0 ... cn | value after loading every element | `pointer(chain)` | yes |
| `pointerAll` | c0 ... cn-1 final | address `[...] + final` (final not loaded) | `pointer_address(chain, final)` | yes |
| `pointerRelative` | c0 ... cn-1 final | same, minus the heap base | `pointer_relative(chain, final)` | yes |
| `pointerPeek` | size c0 ... final | hex at `[...] + final` | `pointer_peek(size, chain, final)` | yes |
| `pointerPeekMulti` | chains joined by `*` (max 40) | concatenated hex | `pointer_peek_multi([(size, chain, final)])` | yes |
| `pointerPoke` | `0x`data c0 ... final | | `pointer_poke(data, chain, final)` | yes (same-value write) |

`pointerPeek` and `pointerPoke` do not check for a broken chain. A chain that hits a null
pointer makes them read or write near address `final`.

## Freezing

| Wire command | Arguments | Client | Tested |
|---|---|---|---|
| `freeze` | heap offset, `0x`data | `freeze(off, data)` | yes |
| `unFreeze` | heap offset | `unfreeze(off)` | yes |
| `freezeCount` | | `freeze_count()` (reply is 2-digit hex) | yes |
| `freezeClear` | | `freeze_clear()` | yes |
| `freezePause` / `freezeUnpause` | | `freeze_pause()` / `freeze_unpause()` | yes |

The address is heap-relative in the code, despite the upstream docs. Frozen values belong to the
title ID that was running when you froze them. The freeze thread waits 30 s after a new game
starts before it writes.

## Controller

| Wire command | Arguments | Client | CLI | Tested |
|---|---|---|---|---|
| `click` | button | `click(b)` | `click B...` | yes |
| `press` / `release` | button | `press(b)` / `release(b)` | `press B`, `release B` | yes |
| `setStick` | `LEFT`/`RIGHT`, x, y | `set_stick(side, x, y)` | `stick left X Y [--ms]` | yes |
| `clickSeq` | one comma string | `click_seq(steps)` | `seq ... --server` | yes |
| `clickCancel` | | `click_cancel()` | `cancel` | yes |
| `detachController` | | `detach_controller()` | `detach` | yes |

Buttons: `A B X Y L R ZL ZR PLUS MINUS LSTICK RSTICK DUP DDOWN DLEFT DRIGHT` (or `DU DD DL DR`),
`HOME CAPTURE PALMA UNUSED`. The client also accepts `up down left right + - start select ls rs`.
Sticks take -0x8000..0x7FFF on each axis; positive y is up.

`clickSeq` syntax: `A` click, `W500` wait ms, `+A` press, `-A` release, `%x,y` left stick,
`&x,y` right stick. It runs in its own thread and prints `done` when it ends.
`sequence(steps)` runs the same steps from the client, one command each (see quirks).

## Touch

| Wire command | Arguments | Client | CLI | Tested |
|---|---|---|---|---|
| `touch` | x y [x y ...] | `touch([(x, y), ...])` | `touch X Y ...` | yes, docked too |
| `touchHold` | x y ms (min 15) | `touch_hold(x, y, ms)` | `touch-hold X Y MS` | yes |
| `touchDraw` | x y x y ... | `touch_draw([(x, y), ...])` | `touch-draw X Y X Y ...` | yes |
| `touchCancel` | | `touch_cancel()` | `cancel` | |

Coordinates are screen pixels, 1280 x 720. Touch runs in a worker thread; the client waits for
the expected duration unless `wait=False`.

## Keyboard

| Wire command | Arguments | Client | CLI | Tested |
|---|---|---|---|---|
| `key` | codes typed in order | `key(*keys)` | `key NAME...` | yes |
| `keyMod` | (code modifier-bit)... | `key_mod([(key, mod)])` | `key-mod A:Shift` | yes, but Shift is ignored |
| `keyMulti` | codes pressed together | `key_multi(*keys)` | `key-multi LeftShift A` | yes |

Codes are HidKeyboardKey values (A=4 ... Z=29, 1..0 = 30..39, Return 40, Backspace 42, Space 44,
LeftShift 225). `type_text("Hello!")` maps a US layout and sends capitals and symbols as
`keyMulti 225 <key>` chords. Tested in the system keyboard (console nickname field).

## Screen

| Wire command | Reply | Client | CLI | Tested |
|---|---|---|---|---|
| `pixelPeek` | hex JPEG, 1280 x 720 | `screenshot()`, `save_screenshot(path)` | `screenshot -o PATH` | yes |
| `screenOff` / `screenOn` | | `screen_off()` / `screen_on()` | `screen off|on` | ran docked |

`screenOff` stops the built-in panel and its backlight. Docked, the TV keeps its picture.

## Information

| Wire command | Reply | Client | Tested |
|---|---|---|---|
| `getVersion` | e.g. `2.6` | `version()` | yes |
| `charge` | battery percent | `charge()` | yes |
| `getSystemLanguage` | SetLanguage number | `system_language()` | yes |
| `isProgramRunning` | `1`/`0` | `is_program_running(id)` | yes |
| `fdCount` | sockets open in sys-botbase | `fd_count()` | yes |
| `getTitleID` | 16 hex digits, empty with no game | `title_id()` | yes |
| `getTitleVersion` | installed version / 0x10000, hex | `title_version()` | yes |
| `getBuildID` | first 8 build-ID bytes, lowercase hex | `build_id()` | yes |
| `getMainNsoBase` | address | `main_nso_base()` | yes |
| `getHeapBase` | address; `4` when the debugger is busy | `heap_base()` (raises `DebuggerBusy`) | yes |
| `game name|author|version|rating|icon` | NACP field; icon is hex JPEG | `game_info(field)`, `game_icon()` | yes |

With no game running, the `game` command answers `nsGetApplicationControlData() failed: 0x6410`
and the others answer an empty line. The client turns these into `NoGameRunning` or `None`.

## configure

| Setting | Default | Effect |
|---|---|---|
| `mainLoopSleepTime` | 50 | ms slept after each command; 0 halves the round trip (about 25 ms) |
| `buttonClickSleepTime` | 50 | ms a `click` holds the button |
| `keySleepTime` | 25 | ms a key is held |
| `pollRate` | 17 | ms per touch / key poll |
| `fingerDiameter` | 50 | touch diameter |
| `freezeRate` | 3 | ms between freeze rewrites |
| `echoCommands` | 0 | 1 echoes each command after its output |
| `printDebugResultCodes` | 0 | 1 prints failing Result codes into the reply stream |
| `controllerType` | 3 | HidDeviceType of the virtual controller; detaches it first |

Settings live in sys-botbase's memory: they apply to every client and last until reboot.
