"""Type text into an open system keyboard, then confirm with PLUS. Usage: type_into_keyboard.py HOST TEXT"""
import sys

from botbase import Botbase

with Botbase(sys.argv[1]) as bb:
    bb.type_text(sys.argv[2])
    bb.click("PLUS")  # OK on the system keyboard; X cancels instead
