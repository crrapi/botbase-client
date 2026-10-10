"""Save a screenshot every N seconds, e.g. to watch a long install. Usage: watch_screen.py HOST [SECONDS]"""
import sys
import time

from botbase import Botbase

host, every = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 10
with Botbase(host) as bb:
    while True:
        print(bb.save_screenshot(time.strftime("watch-%H%M%S.jpg")), flush=True)
        time.sleep(every)
