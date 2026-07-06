"""Protocol unit tests + end-to-end against the built-in simulator. 零硬體可跑。"""
import struct
import subprocess
import sys
import unittest
import zlib
from pathlib import Path

from visordemo import Camera, VisorError
from visordemo.protocol import (gim_request, parse_gim_header,
                                parse_trg_response, png_gray)
from visordemo.simulator import Simulator


class TestProtocol(unittest.TestCase):
    def test_trg_response(self):
        self.assertTrue(parse_trg_response(b"TRGP"))
        self.assertFalse(parse_trg_response(b"TRGF"))
        with self.assertRaises(VisorError):
            parse_trg_response(b"XXXX")

    def test_gim_request(self):
        self.assertEqual(gim_request(0), b"GIM0")
        self.assertEqual(gim_request(2), b"GIM2")
        with self.assertRaises(ValueError):
            gim_request(5)

    def test_gim_header_ok(self):
        # manual example: GIMP...0480 rows, 0640 cols
        rows, cols, itype, good = parse_gim_header(b"GIMP00104800640")
        self.assertEqual((rows, cols, itype, good), (480, 640, 0, True))

    def test_gim_header_fail(self):
        with self.assertRaises(VisorError):
            parse_gim_header(b"GIMF80004800640")

    def test_png_gray_roundtrip(self):
        rows, cols = 2, 3
        data = bytes(range(6))
        png = png_gray(rows, cols, data)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        w, h = struct.unpack(">II", png[16:24])
        self.assertEqual((w, h), (cols, rows))
        idat = png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8]
        raw = zlib.decompress(idat)
        self.assertEqual(raw, b"\x00\x00\x01\x02\x00\x03\x04\x05")  # filter0 + rows

    def test_png_gray_size_check(self):
        with self.assertRaises(ValueError):
            png_gray(2, 3, b"\x00")


class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = Simulator(host="127.0.0.1", port=0, rows=48, cols=64).start()

    @classmethod
    def tearDownClass(cls):
        cls.sim.stop()

    def test_capture(self):
        with Camera("127.0.0.1", self.sim.port) as cam:
            frame = cam.capture()
        self.assertEqual((frame.rows, frame.cols), (48, 64))
        self.assertTrue(frame.good)
        self.assertEqual(len(frame.data), 48 * 64)
        self.assertTrue(frame.to_png().startswith(b"\x89PNG"))

    def test_trigger_advances_pattern(self):
        with Camera("127.0.0.1", self.sim.port) as cam:
            a = cam.capture().data
            b = cam.capture().data
        self.assertNotEqual(a, b)

    def test_no_trigger_same_image(self):
        with Camera("127.0.0.1", self.sim.port, auto_trigger=False) as cam:
            a = cam.get_frame().data
            b = cam.get_frame().data
        self.assertEqual(a, b)

    def test_cli_snapshot(self):
        out = Path(self.id() + ".png")
        try:
            r = subprocess.run(
                [sys.executable, "-m", "visordemo.cli", "snapshot",
                 "--host", "127.0.0.1", "--port", str(self.sim.port),
                 "-o", str(out)],
                capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("64x48", r.stdout)
            self.assertTrue(out.read_bytes().startswith(b"\x89PNG"))
        finally:
            out.unlink(missing_ok=True)

    def test_webcamdemo_compat_surface(self):
        """qc-station photo.py 的呼叫序列可以原樣走完。"""
        with Camera("127.0.0.1", self.sim.port) as cam:
            try:
                cam.set_control("brightness", 160)
            except Exception:
                pass  # photo.py 同樣 try/except
            cam.start_stream(3840, 2160)
            png = cam.read_png()
            cam.stop_stream()
        self.assertTrue(png.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
