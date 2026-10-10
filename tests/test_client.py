"""Protocol tests against tests/fake_server.py. Run: python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from botbase import Botbase, DebuggerBusy, MemoryAccessError, NoGameRunning  # noqa: E402
from botbase.cli import encode_value, parse_seq, show_bytes  # noqa: E402
from botbase.client import key_code, normalize_button  # noqa: E402
from fake_server import HEAP, MAIN, FakeBotbase  # noqa: E402


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeBotbase()
        self.bb = Botbase("127.0.0.1", self.server.port, timeout=3)

    def tearDown(self):
        self.bb.close()
        self.server.close()

    def test_silent_command_is_fenced(self):
        self.bb.click("a")
        self.assertEqual(self.server.lines[-2:], ["click A", "getVersion"])

    def test_unknown_button_is_refused(self):
        with self.assertRaises(ValueError):
            self.bb.click("PLSU")  # sys-botbase would press A
        self.assertNotIn("click PLSU", self.server.lines)

    def test_info_commands(self):
        self.assertEqual(self.bb.version(), "2.6")
        self.assertEqual(self.bb.charge(), 87)
        self.assertEqual(self.bb.system_language(), (1, "American English"))
        self.assertEqual(self.bb.title_id(), 0x0100000000010000)
        self.assertEqual(self.bb.title_version(), 31)
        self.assertEqual(self.bb.build_id(), "21450c647b8c5940")
        self.assertEqual(self.bb.heap_base(), HEAP)
        self.assertTrue(self.bb.is_program_running(0x0100000000010000))
        self.assertEqual(self.bb.game_info("name"), "Test Game")
        self.assertEqual(self.bb.info()["memory_access"], True)

    def test_peek_poke_regions(self):
        self.bb.poke(0x40, b"\x01\x02\x03\x04")
        self.assertEqual(self.server.read(HEAP + 0x40, 4), b"\x01\x02\x03\x04")
        self.assertEqual(self.bb.peek(0x40, 4), b"\x01\x02\x03\x04")
        self.bb.write_int(0x8, 0x4D4F4430, region="main")
        self.assertEqual(self.bb.read_int(0x8, region="main"), 0x4D4F4430)
        self.bb.write_float(0x50, 1.5)
        self.assertEqual(self.bb.read_float(0x50), 1.5)
        self.assertEqual(self.bb.peek(MAIN + 0x8, 4, region="absolute"), b"0DOM")

    def test_peek_multi_splits(self):
        self.server.write(HEAP, bytes(range(16)))
        a, b = self.bb.peek_multi([(0, 2), (8, 3)])
        self.assertEqual((a, b), (b"\x00\x01", b"\x08\x09\x0a"))

    def test_failed_read_raises(self):
        with self.assertRaises(MemoryAccessError):
            self.bb.peek(0x999999, 4)

    def test_pointer_helpers(self):
        self.server.write(HEAP + 0x110, b"\xaa\xbb")
        self.assertEqual(self.bb.pointer_address([0x10, -0x20], final=0x10), HEAP + 0x110)
        self.assertIn("pointerAll 0x10 -0x20 0x10", self.server.lines)
        self.assertEqual(self.bb.pointer_peek(2, [0x10], final=0x10), b"\xaa\xbb")

    def test_freeze(self):
        self.bb.freeze(0x20, b"\x63")
        self.assertEqual(self.bb.freeze_count(), 1)
        self.bb.freeze_clear()
        self.assertEqual(self.bb.freeze_count(), 0)

    def test_click_seq_waits_for_done(self):
        self.bb.click_seq(["DR", 300, ("press", "L"), ("stick", "left", -0x9000, 100), ("release", "L")])
        self.assertIn("clickSeq DR,W300,+L,%-32768,100,-L", self.server.lines)
        self.assertEqual(self.bb.click_seq_done, 1)
        self.assertEqual(self.bb.version(), "2.6")  # the "done" line never leaks into replies

    def test_type_text_uses_shift_chords(self):
        self.bb.type_text("aB!", wait=False)
        self.assertIn("key 4", self.server.lines)
        self.assertIn("keyMulti 225 5", self.server.lines)
        self.assertIn("keyMulti 225 30", self.server.lines)

    def test_screenshot(self):
        self.assertTrue(self.bb.screenshot().startswith(b"\xff\xd8\xff"))

    def test_touch_bounds(self):
        with self.assertRaises(ValueError):
            self.bb.touch([(1300, 10)], wait=False)
        self.bb.touch([(100, 200), (300, 400)], wait=False)
        self.assertIn("touch 100 200 300 400", self.server.lines)

    def test_line_length_guard(self):
        with self.assertRaises(ValueError):
            self.bb.send_line("x" * 30000)


class BusyAndIdleTests(unittest.TestCase):
    def test_debugger_busy(self):
        server = FakeBotbase(debugger_busy=True)
        with Botbase("127.0.0.1", server.port, timeout=3) as bb:
            with self.assertRaises(DebuggerBusy):
                bb.heap_base()
            self.assertEqual(bb.info()["memory_access"], False)
        server.close()

    def test_no_game(self):
        server = FakeBotbase(game_running=False)
        with Botbase("127.0.0.1", server.port, timeout=3) as bb:
            self.assertIsNone(bb.title_id())
            with self.assertRaises(NoGameRunning):
                bb.game_info("name")
            with self.assertRaises(NoGameRunning):
                bb.require_memory_access()
            self.assertIsNone(bb.info()["title_id"])
        server.close()


class HelperTests(unittest.TestCase):
    def test_button_aliases(self):
        self.assertEqual(normalize_button("up"), "DUP")
        self.assertEqual(normalize_button("+"), "PLUS")
        self.assertEqual(normalize_button("dr"), "DR")

    def test_key_codes(self):
        self.assertEqual(key_code("Return"), 40)
        self.assertEqual(key_code("a"), 4)
        self.assertEqual(key_code("225"), 225)
        with self.assertRaises(ValueError):
            key_code(2)

    def test_parse_seq(self):
        self.assertEqual(parse_seq(["A,W250,+L,%-100,-200,-L,&0,0"]),
                         ["A", 250, ("press", "L"), ("stick", "left", -100, -200), ("release", "L"),
                          ("stick", "right", 0, 0)])

    def test_value_codecs(self):
        self.assertEqual(encode_value("0x10", "u32"), b"\x10\x00\x00\x00")
        self.assertEqual(encode_value("ff01", "hex"), b"\xff\x01")
        self.assertEqual(show_bytes(b"\x00\x00\xc0\x3f", "f32"), "1.5")


if __name__ == "__main__":
    unittest.main()
