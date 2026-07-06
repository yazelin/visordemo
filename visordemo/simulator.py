"""Fake VISOR TCP server: answers TRG / GIMx with a moving test pattern.

實機不在手邊時拿來開發與跑測試;協定與手冊 ASCII 格式一致。
"""
import socket
import threading


class Simulator:
    def __init__(self, host="0.0.0.0", port=2006, rows=480, cols=640):
        self.rows = rows
        self.cols = cols
        self._counter = 0
        self._server = socket.create_server((host, port))
        self.port = self._server.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._server.close()

    def _frame_data(self) -> bytes:
        # 對角漸層 + 隨 trigger 次數平移,連拍兩張看得出差異
        shift = self._counter * 8
        return bytes(((r + c + shift) & 0xFF)
                     for r in range(self.rows) for c in range(self.cols))

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        with conn:
            while not self._stop.is_set():
                try:
                    req = conn.recv(64)
                except OSError:
                    return
                if not req:
                    return
                if req.startswith(b"TRG"):
                    self._counter += 1
                    conn.sendall(b"TRGP")
                elif req.startswith(b"GIM"):
                    header = (b"GIMP" + b"0" + b"0" + b"1"
                              + f"{self.rows:04d}{self.cols:04d}".encode())
                    conn.sendall(header + self._frame_data())
                else:
                    conn.sendall(req[:3] + b"F")


def main(host="0.0.0.0", port=2006):
    sim = Simulator(host, port).start()
    print(f"VISOR simulator listening on {host}:{sim.port} (TRG / GIM)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        sim.stop()
