"""VISOR TCP camera client — webcamdemo-compatible surface.

qc-station photo.py 的 camera_factory 換成本類別即可:
context manager、set_control、start_stream/stop_stream 皆有(後三者為
no-op / 明確拒絕),read_png() 取代 read_jpeg()。
"""
import socket

from .protocol import (Frame, VisorError, gim_request, parse_gim_header,
                       parse_trg_response, trg_request)


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
