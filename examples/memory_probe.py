"""Check that sys-botbase can read the running game's memory, and show where the heap starts.
Usage: memory_probe.py HOST"""
import sys

from botbase import Botbase, DebuggerBusy, MemoryAccessError

with Botbase(sys.argv[1]) as bb:
    try:
        heap = bb.require_memory_access()
    except DebuggerBusy as e:
        sys.exit(str(e))
    print(f"heap region {heap:#x}, main NSO {bb.main_nso_base():#x}")
    mod0 = bb.read_int(4, region="main")
    print("MOD0 magic:", bb.peek(mod0, 4, region="main"))
    for shift in range(12, 32):  # find the first mapped page of the heap region
        try:
            bb.peek(1 << shift, 4)
            print(f"first readable heap offset found at {1 << shift:#x}")
            break
        except MemoryAccessError:
            continue
