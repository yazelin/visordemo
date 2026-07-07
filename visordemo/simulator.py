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
        self.focus_um = 754600   # working distance in mm*1000
        self.shutter_us = 43403  # ms*1000
        self.gain_x1000 = 1000
        self.active_job = 1
        self.jobs = ["Job1", "Job2"]
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
                elif req.startswith(b"GFC"):
                    conn.sendall(b"GFCP000" + f"{self.focus_um:08d}".encode())
                elif req.startswith(b"SFC"):
                    self.focus_um = int(req[7:15])
                    conn.sendall(b"SFCP000" + f"{self.focus_um:08d}".encode())
                elif req.startswith(b"AFC"):
                    self.focus_um = 500000
                    conn.sendall(b"AFCP000001"
                                 + f"{self.focus_um:08d}".encode() + b"00099000")
                elif req.startswith(b"GJL"):
                    body = f"001{len(self.jobs):03d}{self.active_job:03d}".encode()
                    for name in self.jobs:
                        nb = name.encode()
                        body += (f"{len(nb):03d}".encode() + nb
                                 + b"004desc" + b"002me" + b"20260101" + b"20260102")
                    conn.sendall(b"GJLP" + body)
                elif req.startswith(b"CJB") or req.startswith(b"CJP"):
                    n = int(req[3:6])
                    if 1 <= n <= len(self.jobs):
                        self.active_job = n
                        conn.sendall(req[:3] + b"PT" + f"{n:03d}".encode())
                    else:
                        conn.sendall(req[:3] + b"F")
                elif req.startswith(b"CJN"):
                    name = req[7:].decode("utf-8", "replace")
                    if name in self.jobs:
                        self.active_job = self.jobs.index(name) + 1
                        conn.sendall(b"CJNP000T")
                    else:
                        conn.sendall(b"CJNF001T")
                elif req.startswith(b"GSH"):
                    conn.sendall(b"GSHP" + f"{self.shutter_us}".encode())
                elif req.startswith(b"SST") or req.startswith(b"SSP"):
                    self.shutter_us = int(req[5:5 + int(req[3:5])])
                    conn.sendall(req[:3] + b"P")
                elif req.startswith(b"ASH"):
                    self.shutter_us = 20000
                    conn.sendall(b"ASHP" + f"{self.shutter_us}".encode())
                elif req.startswith(b"GGA"):
                    conn.sendall(b"GGAP" + f"{self.gain_x1000:05d}".encode())
                elif req.startswith(b"SGA"):
                    self.gain_x1000 = int(req[4:9])
                    conn.sendall(b"SGAP")
                elif req.startswith(b"GSI"):
                    ident = b"visordemo-simulator fw 9.9"
                    conn.sendall(b"GSIP000" + f"{len(ident):03d}".encode() + ident)
                elif req.startswith(b"CGP"):
                    vals = [12119, -922359, 3449, 3449, 698908, 542990,
                            self.cols, self.rows]
                    body = b"".join(f"{v:08d}".encode() if v >= 0
                                    else f"{v:+08d}".encode() for v in vals)
                    conn.sendall(b"CGPP000010" + f"{len(body):08d}".encode() + body)
                else:
                    conn.sendall(req[:3] + b"F")


def main(host="0.0.0.0", port=2006):
    sim = Simulator(host, port).start()
    print(f"VISOR simulator listening on {host}:{sim.port} (TRG / GIM)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        sim.stop()
