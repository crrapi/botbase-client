# Server side: installing sys-botbase

## Install

1. Get `sys-botbase.nsp` from https://github.com/olliz0r/sys-botbase/releases.
2. Put it on the SD card as `atmosphere/contents/430000000000000B/exefs.nsp`.
3. Create an empty `atmosphere/contents/430000000000000B/flags/boot2.flag` (autostart).
4. Reboot into Atmosphere. The HOME button of attached Joy-Cons glows when it starts.
5. `botbase discover` should list the console.

Copy files with the SD card mounted on a computer (hekate: Tools, USB Tools, SD Card) when you
can. Creating files under `atmosphere/` over FTP while the console runs has been linked to FAT
directory damage on at least one console.

## HOS 21 and later: boot crash 2001-0132

With the official v2.5 on HOS 22.x, the console can crash about 30 s into boot with
**2001-0132** (`0x10801`) in `am` (`0100000000000023`) or `hid` (`0100000000000013`). `audio`
and `omm` often abort with it. 2001-0132 is `svc::ResultLimitReached`: a System resource limit
reservation failed.

The cause is memory. Atmosphere's PM gives all homebrew sysmodules together a fixed extra
32 MB of System memory (`stratosphere/pm/source/impl/pm_spec.cpp`,
`ExtraSystemMemorySizeAtmosphere = 32_MB`, not configurable). Newer HOS versions use more of the
System pool themselves, so the margin is small. Official v2.5 needs about 4.7 MB of image
(a 4.5 MB static heap) plus about 2 MB of socket buffers. Whichever system process allocates last
then fails.

### Fix 1: a smaller sys-botbase build

Open PR #111 (https://github.com/olliz0r/sys-botbase/pull/111) lowers the heap to 2 MB and
shrinks the socket buffers; the image drops to 2.16 MB and it reports version `2.6`. Build it:

```sh
curl -sSfL -o src.tar.gz https://codeload.github.com/olliz0r/sys-botbase/tar.gz/ae13548c587b75abf54f32032ad8d52f51eda05e
tar xzf src.tar.gz && cd sys-botbase-ae13548c*/
curl -sSfL https://github.com/quinnfrost/sys-botbase/commit/1eacdc6751ebfbee4cebae674dfce5856280c95e.patch | patch -p1
make -C sys-botbase      # devkitPro devkitA64 + libnx 4.10 or later
# result: sys-botbase/sys-botbase.nsp -> atmosphere/contents/430000000000000B/exefs.nsp
```

### Fix 2: free memory elsewhere

On a console with ten other sysmodules enabled, the smaller build alone still crashed (now in `hid`).
Disabling two unused sysmodules (about 2.2 MB) made it boot cleanly. Static image sizes
(NSO segments plus .bss) measured on that console, to help choose:

| Sysmodule | MB |
|---|---|
| ldn_mitm | 1.63 |
| sys-con | 1.40 |
| sys-ftpd | 0.94 |
| sys-tune | 0.77 |
| MissionControl | 0.68 |
| emuiibo | 0.51 |
| sys-clk | 0.47 |
| SaltyNX | 0.38 |
| sys-patch | 0.10 |
| nx-ovlloader | 0.05, plus a 4 MB overlay heap held from boot (4 MB is its minimum) |

To disable a sysmodule, rename its `flags/boot2.flag` to `flags/boot2.flag.disabled`.
Upstream reports the same crash with ldn_mitm (GBAtemp, HOS 22.1.0), with nx-ovlloader (#97) and
with large Ultrahand setups (#96).

### Checking a boot

sys-botbase answers even while the console sits on a fatal screen, so a working `getVersion`
proves nothing. After about 60 s, look for new files in `atmosphere/crash_reports/` and
`atmosphere/fatal_reports/`.
