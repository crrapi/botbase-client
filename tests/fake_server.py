"""A small stand-in for sys-botbase, good enough to test the client's protocol handling.

It mimics the parts of sys-botbase that matter to a client: one reply line for read commands,
silence for everything else, "done" after a clickSeq finishes, an empty line for failed reads,
and 0x4 from getHeapBase when another debugger holds the game.
"""
import socket
import threading
import time

HEAP, MAIN = 0x1000000000, 0x7000000000


class FakeBotbase:
    def __init__(self, debugger_busy=False, game_running=True):
        self.debugger_busy, self.game_running = debugger_busy, game_running
        self.lines = []
        self.memory = {}  # absolute address -> byte
        self.freezes = {}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def close(self):
        self.sock.close()

    def write(self, addr, data):
        for i, b in enumerate(data):
            self.memory[addr + i] = b

    def read(self, addr, size):
        if any(addr + i not in self.memory for i in range(size)):
            return None
        return bytes(self.memory[addr + i] for i in range(size))

    def _serve(self):
        try:
            while True:
                conn, _ = self.sock.accept()
                threading.Thread(target=self._client, args=(conn,), daemon=True).start()
        except OSError:
            pass

    def _client(self, conn):
        with conn:
            self._session(conn)

    def _session(self, conn):
        buf = b""
        while True:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode().rstrip("\r")
                self.lines.append(text)
                out = self._handle(text, conn)
                if out is not None:
                    conn.sendall(out.encode() + b"\n")

    def _peek(self, base, args):
        out = ""
        for off, size in zip(args[::2], args[1::2]):
            data = self.read(base + int(off, 0), int(size, 0))
            if data is None:
                return ""
            out += data.hex().upper()
        return out

    def _handle(self, text, conn):
        argv = text.split()
        cmd, args = argv[0], argv[1:]
        game = self.game_running
        if cmd == "getVersion":
            return "2.6"
        if cmd == "charge":
            return "87"
        if cmd == "getSystemLanguage":
            return "1"
        if cmd == "fdCount":
            return "2"
        if cmd == "freezeCount":
            return f"{len(self.freezes):02X}"
        if cmd == "isProgramRunning":
            return "1" if int(args[0], 0) == 0x0100000000010000 else "0"
        if cmd == "getTitleID":
            return "0100000000010000" if game else ""
        if cmd == "getTitleVersion":
            return "000000000000001F" if game else ""
        if cmd == "getBuildID":
            return "21450c647b8c5940" if game else ""
        if cmd == "getMainNsoBase":
            return f"{MAIN:016X}" if game else ""
        if cmd == "getHeapBase":
            if not game:
                return ""
            return "0000000000000004" if self.debugger_busy else f"{HEAP:016X}"
        if cmd == "game":
            if not game:
                return "nsGetApplicationControlData() failed: 0x6410"
            return {"name": "Test Game", "author": "Nobody", "version": "1.2.3", "rating": "0",
                    "icon": "FFD8FFE000104A464946"}[args[0]]
        if cmd == "pixelPeek":
            return "FFD8FFE000104A4649460001" + "00" * 32
        if cmd in ("peek", "peekMulti"):
            return self._peek(HEAP, args)
        if cmd in ("peekMain", "peekMainMulti"):
            return self._peek(MAIN, args)
        if cmd in ("peekAbsolute", "peekAbsoluteMulti"):
            return self._peek(0, args)
        if cmd in ("poke", "pokeMain", "pokeAbsolute"):
            base = {"poke": HEAP, "pokeMain": MAIN, "pokeAbsolute": 0}[cmd]
            self.write(base + int(args[0], 0), bytes.fromhex(args[1][2:]))
            return None
        if cmd == "pointerAll":
            return f"{HEAP + 0x100 + int(args[-1], 0):016X}"
        if cmd == "pointerPeek":
            data = self.read(HEAP + 0x100 + int(args[-1], 0), int(args[0], 0))
            return data.hex().upper() if data else ""
        if cmd == "freeze":
            self.freezes[int(args[0], 0)] = args[1]
            return None
        if cmd == "freezeClear":
            self.freezes.clear()
            return None
        if cmd == "clickSeq":
            def finish():
                time.sleep(0.2)
                conn.sendall(b"done\n")
            threading.Thread(target=finish, daemon=True).start()
            return None
        return None  # every other command is silent
