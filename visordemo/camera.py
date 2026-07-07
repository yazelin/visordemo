"""VISOR TCP camera client — webcamdemo-compatible surface.

qc-station photo.py 的 camera_factory 換成本類別即可:
context manager、set_control、start_stream/stop_stream 皆有(後三者為
no-op / 明確拒絕),read_png() 取代 read_jpeg()。
"""
import socket

from .protocol import (Frame, VisorError, afc_request, gfc_request,
                       gim_request, parse_focus_response, parse_gim_header,
                       parse_trg_response, sfc_request, trg_request)


class Camera:
    """One TCP connection to the VISOR request/response channel (port 2006).

    eot: end-of-telegram bytes if configured in SensoConfig (usually b"").
    auto_trigger: capture() sends TRG before GIM so the image is fresh;
    set False if the sensor free-runs (continuous trigger mode).
    """

    def __init__(self, host, port=2006, timeout=5.0, eot=b"", auto_trigger=True):
        self.host = host
        self.port = port
        self.eot = eot
        self.auto_trigger = auto_trigger
        self._shutter_fmt = None  # "new"/"old",第一次 set_shutter 時偵測
        self._sock = socket.create_connection((host, port), timeout=timeout)

    # -- context manager ----------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    # -- wire helpers --------------------------------------------------
    def _send(self, payload: bytes):
        self._sock.sendall(payload + self.eot)

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise VisorError("connection closed by sensor")
            buf += chunk
        return buf

    # -- VISOR commands -------------------------------------------------
    def trigger(self) -> bool:
        """TRG. Returns True on Pass."""
        self._send(trg_request())
        ok = parse_trg_response(self._recv_exact(4))
        if self.eot:
            self._recv_exact(len(self.eot))
        return ok

    def get_frame(self, which: int = 0) -> Frame:
        """GIM. which: 0=last, 1=last bad, 2=last good image."""
        self._send(gim_request(which))
        rows, cols, image_type, good = parse_gim_header(self._recv_exact(15))
        if self.eot:
            self._recv_exact(len(self.eot))
        data = self._recv_exact(rows * cols)
        return Frame(rows, cols, image_type, good, data)

    def _ask(self, payload: bytes, quiet: float = 0.4) -> bytes:
        """Send + drain reply until brief silence(變長回應用,控制指令皆短)."""
        self._send(payload)
        old = self._sock.gettimeout()
        buf = b""
        try:
            self._sock.settimeout(quiet)
            while True:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
        except socket.timeout:
            pass
        finally:
            self._sock.settimeout(old)
        if not buf:
            raise VisorError(f"no response to {payload[:4]!r}")
        return buf

    @staticmethod
    def _check(resp: bytes, cmd: bytes) -> bytes:
        if resp[:3] != cmd or resp[3:4] != b"P":
            raise VisorError(f"{cmd.decode()} failed: {resp!r}")
        return resp

    # -- job management --------------------------------------------------
    def jobs(self) -> tuple[int, list[str]]:
        """GJL: (active job number, [job names])."""
        resp = self._check(self._ask(b"GJL1"), b"GJL")
        count, active = int(resp[7:10]), int(resp[10:13])
        names, pos = [], 13
        try:
            for _ in range(count):
                ln = int(resp[pos:pos + 3]); pos += 3
                names.append(resp[pos:pos + ln].decode("utf-8", "replace")); pos += ln
                for _ in range(2):  # description, author
                    fl = int(resp[pos:pos + 3]); pos += 3 + fl
                pos += 16  # created + modified dates
        except (ValueError, IndexError) as e:
            raise VisorError(f"GJL parse error at byte {pos}: {resp!r}") from e
        return active, names

    def set_job(self, job, permanent: bool = False) -> None:
        """CJB/CJP by number, CJN by name."""
        if isinstance(job, int):
            cmd = b"CJP" if permanent else b"CJB"
            self._check(self._ask(cmd + f"{job:03d}".encode()), cmd)
        else:
            name = str(job).encode("utf-8")
            self._check(self._ask(b"CJN1" + f"{len(name):03d}".encode() + name),
                        b"CJN")

    # -- shutter / gain ---------------------------------------------------
    def get_shutter(self) -> float:
        """GSH: shutter speed in ms."""
        resp = self._check(self._ask(b"GSH"), b"GSH")
        return int(resp[4:]) / 1000

    def set_shutter(self, ms: float, permanent: bool = False) -> float:
        """SST/SSP: set shutter speed in ms. Returns actual value.

        新舊韌體格式不同(新=2位數長度前綴+數值、舊=裸數值≥6位),
        逐一嘗試並以 GSH 讀回驗證,測到能用的格式就記住。
        """
        target = round(ms * 1000)
        cmd = b"SSP" if permanent else b"SST"
        new_fmt = f"{len(str(target)):02d}{target}".encode()
        old_fmt = b"%06d" % target
        formats = [new_fmt, old_fmt] if self._shutter_fmt != "old" else [old_fmt]
        for payload in formats:
            try:
                self._check(self._ask(cmd + payload), cmd)
            except VisorError:
                continue
            got = round(self.get_shutter() * 1000)
            if abs(got - target) <= max(100, target * 0.05):
                self._shutter_fmt = "new" if payload is new_fmt else "old"
                return got / 1000
        raise VisorError(f"set shutter {target}us failed on both telegram formats"
                         f" (sensor now at {self.get_shutter()}ms)")

    def auto_shutter(self, permanent: bool = False) -> None:
        """ASH: auto-determine shutter speed."""
        self._check(self._ask(b"ASH1" + (b"1" if permanent else b"0"), quiet=10.0),
                    b"ASH")

    def get_gain(self) -> float:
        """GGA: gain factor."""
        resp = self._check(self._ask(b"GGA"), b"GGA")
        return int(resp[4:]) / 1000

    def set_gain(self, gain: float, permanent: bool = False) -> float:
        """SGA: set gain factor, e.g. 2.0. Returns actual value (readback-verified)."""
        self._check(self._ask(b"SGA" + (b"1" if permanent else b"0")
                              + f"{round(gain * 1000):05d}".encode()), b"SGA")
        got = self.get_gain()
        if abs(got - gain) > max(0.05, gain * 0.05):
            raise VisorError(f"gain readback {got} != requested {gain}")
        return got

    # -- device info -------------------------------------------------------
    def identity(self) -> str:
        """GSI: firmware + hardware type. 舊韌體可能不支援(回 Fail)."""
        resp = self._check(self._ask(b"GSI1"), b"GSI")
        return resp[10:].decode("utf-8", "replace")

    def internal_params(self) -> dict:
        """CGP 010: focal length, pixel pitch, image size(校正內參)."""
        resp = self._check(self._ask(b"CGP1010"), b"CGP")
        v = [int(resp[18 + i * 8:26 + i * 8]) for i in range(8)]
        return {"focal_mm": v[0] / 1000, "kappa": v[1] / 1000,
                "pitch_x_um": v[2] / 1000, "pitch_y_um": v[3] / 1000,
                "origin_x": v[4] / 1000, "origin_y": v[5] / 1000,
                "width_px": v[6], "height_px": v[7]}

    def fov(self, distance_mm: float | None = None) -> tuple[float, float]:
        """(FOV width, height) in mm at the given (or current) working distance."""
        p = self.internal_params()
        d = distance_mm if distance_mm is not None else self.get_focus()
        w = p["width_px"] * p["pitch_x_um"] / 1000 * d / p["focal_mm"]
        h = p["height_px"] * p["pitch_y_um"] / 1000 * d / p["focal_mm"]
        return round(w, 1), round(h, 1)

    def get_focus(self) -> float:
        """GFC: read working distance in mm (motorized-focus models only)."""
        self._send(gfc_request())
        return self._read_focus(b"GFC")

    def set_focus(self, mm: float, permanent: bool = False) -> float:
        """SFC: set absolute working distance in mm. Returns actual value."""
        self._send(sfc_request(mm, permanent))
        return self._read_focus(b"SFC")

    def autofocus(self, permanent: bool = False) -> float:
        """AFC: run autofocus, returns found working distance in mm. Slow."""
        old = self._sock.gettimeout()
        self._sock.settimeout(60.0)  # AF 掃整個行程,實測可能十幾秒
        try:
            self._send(afc_request(permanent))
            return self._read_focus(b"AFC")
        finally:
            self._sock.settimeout(old)

    def _read_focus(self, cmd: bytes) -> float:
        resp = self._recv_exact(15)
        if cmd == b"AFC" and resp[3:4] == b"P":
            # AFC 全長 26:AFCP + err(3) + count(3) + dist(8) + score(8)
            resp += self._recv_exact(11)
            if self.eot:
                self._recv_exact(len(self.eot))
            return int(resp[10:18]) / 1000
        if self.eot:
            self._recv_exact(len(self.eot))
        return parse_focus_response(resp, cmd)

    def capture(self, which: int = 0) -> Frame:
        if self.auto_trigger:
            self.trigger()
        return self.get_frame(which)

    def read_png(self) -> bytes:
        """One fresh capture as PNG bytes."""
        return self.capture().to_png()

    # -- webcamdemo-compat no-ops ----------------------------------------
    def start_stream(self, width=None, height=None, fps=None):
        pass  # ponytail: VISOR 解析度由 job 決定,無串流可開

    def stop_stream(self):
        pass

    def set_control(self, ctrl_id, value):
        # qc-station photo.py 對 set_control 有 try/except,raise 即被跳過
        raise NotImplementedError(
            "VISOR controls are configured as jobs via SensoConfig")
