"""Protocol unit tests + end-to-end against the built-in simulator. 零硬體可跑。"""
import struct
import subprocess
import sys
import unittest
import zlib
from pathlib import Path

from visordemo import Camera, VisorError
from visordemo.protocol import (demosaic_half, gim_request, parse_gim_header,
                                parse_trg_response, png_gray, png_rgb)
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

    def test_demosaic_half(self):
        # 2x2 Bayer BG quad: B=10 G=20 / G=30 R=40 -> one RGB pixel
        r, c, rgb = demosaic_half(2, 2, bytes([10, 20, 30, 40]))
        self.assertEqual((r, c), (1, 1))
        self.assertEqual(rgb, bytes([40, 25, 10]))  # R, avg(G), B

    def test_png_rgb(self):
        png = png_rgb(1, 1, bytes([255, 0, 0]))
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertEqual(png[25], 2)  # IHDR color type = truecolor


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

    def test_focus_roundtrip(self):
        with Camera("127.0.0.1", self.sim.port, auto_trigger=False) as cam:
            orig = cam.get_focus()
            self.assertEqual(cam.set_focus(1830), 1830.0)
            self.assertEqual(cam.get_focus(), 1830.0)
            self.assertEqual(cam.autofocus(), 500.0)
            cam.set_focus(orig)

    def test_jobs_and_switch(self):
        with Camera("127.0.0.1", self.sim.port, auto_trigger=False) as cam:
            active, names = cam.jobs()
            self.assertEqual(names, ["Job1", "Job2"])
            cam.set_job(2)
            self.assertEqual(cam.jobs()[0], 2)
            cam.set_job("Job1")
            self.assertEqual(cam.jobs()[0], 1)
            with self.assertRaises(VisorError):
                cam.set_job(99)

    def test_shutter_gain(self):
        with Camera("127.0.0.1", self.sim.port, auto_trigger=False) as cam:
            cam.set_shutter(8.0)
            self.assertEqual(cam.get_shutter(), 8.0)
            cam.auto_shutter()
            self.assertEqual(cam.get_shutter(), 20.0)
            cam.set_gain(2.0)
            self.assertEqual(cam.get_gain(), 2.0)

    def test_info_and_fov(self):
        with Camera("127.0.0.1", self.sim.port, auto_trigger=False) as cam:
            self.assertIn("simulator", cam.identity())
            p = cam.internal_params()
            self.assertEqual(p["focal_mm"], 12.119)
            w, h = cam.fov(1830)
            self.assertAlmostEqual(w, 33.3, delta=1)   # 64px 模擬感光面
            self.assertGreater(w / h, 1.2)

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


class TestServerSingleFlight(unittest.TestCase):
    """相機命令 port 單飛:忙碌時並發請求回 409 而非疊上去打爆相機。"""

    def setUp(self):
        import threading
        from http.server import ThreadingHTTPServer
        from functools import partial
        from visordemo import server as server_mod
        from visordemo.server import Handler

        self.sim = Simulator(host="127.0.0.1", port=0, rows=32, cols=32).start()
        self.addCleanup(self.sim.stop)
        self.server_mod = server_mod
        handler = partial(Handler, host="127.0.0.1", port=self.sim.port,
                          auto_trigger=True)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        t.start()
        self.addCleanup(self.httpd.shutdown)

    def _get(self, path):
        import urllib.request
        import urllib.error
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}")
            return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_busy_camera_returns_409(self):
        # 佔住相機鎖,模擬「有人正在調參數/自動對焦」
        self.server_mod._CAM_LOCK.acquire()
        try:
            self.assertEqual(self._get("/api/info"), 409)
            self.assertEqual(self._get("/snapshot.png"), 409)
        finally:
            self.server_mod._CAM_LOCK.release()
        # 放開後恢復正常
        self.assertEqual(self._get("/api/info"), 200)


if __name__ == "__main__":
    unittest.main()
