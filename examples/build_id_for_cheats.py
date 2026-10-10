"""Print the running game's title ID and build ID, in the form Atmosphere uses for cheat files:
atmosphere/contents/<TITLE ID>/cheats/<BUILD ID>.txt. Usage: build_id_for_cheats.py HOST"""
import sys

from botbase import Botbase

with Botbase(sys.argv[1]) as bb:
    tid = bb.title_id()
    if tid is None:
        sys.exit("no game is running")
    print(f"{bb.game_info('name')} v{bb.game_info('version')}")
    print(f"atmosphere/contents/{tid:016X}/cheats/{bb.build_id().upper()}.txt")
