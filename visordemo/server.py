"""Web UI: 即時預覽 SensoPart VISOR 影像(輪詢 /snapshot.png)。"""
import json
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources

from .camera import Camera
from .protocol import VisorError


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, host, port, auto_trigger, **kwargs):
        self.visor_host = host
        self.visor_port = port
        self.auto_trigger = auto_trigger
        super().__init__(*args, **kwargs)

    def log_message(self, *a):
        pass

    def _reply(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            html = (resources.files("visordemo") / "static/index.html").read_bytes()
            self._reply(200, "text/html; charset=utf-8", html)
        elif self.path.startswith("/api/"):
            self._api()
        elif self.path.startswith("/snapshot.png"):
            # ponytail: 每張開新連線,開-拍-關,斷線自癒;要更快再改常駐連線
            try:
                with Camera(self.visor_host, self.visor_port,
                            auto_trigger=self.auto_trigger) as cam:
                    self._reply(200, "image/png", cam.read_png())
            except (OSError, VisorError) as e:
                body = json.dumps({"ok": False, "error": str(e)}).encode()
                self._reply(502, "application/json", body)
        else:
            self._reply(404, "text/plain", b"not found")

    def _api(self):
        from urllib.parse import parse_qs, urlparse
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            with Camera(self.visor_host, self.visor_port,
                        auto_trigger=False) as cam:
                if u.path == "/api/focus":
                    if "auto" in q:
                        out = {"mm": cam.autofocus()}
                    elif "set" in q:
                        out = {"mm": cam.set_focus(float(q["set"][0]))}
                    else:
                        out = {"mm": cam.get_focus()}
                elif u.path == "/api/shutter":
                    if "auto" in q:
                        cam.auto_shutter()
                    elif "set" in q:
                        cam.set_shutter(float(q["set"][0]))
                    out = {"ms": cam.get_shutter()}
                elif u.path == "/api/gain":
                    if "set" in q:
                        cam.set_gain(float(q["set"][0]))
                    out = {"gain": cam.get_gain()}
                elif u.path == "/api/job":
                    if "set" in q:
                        raw = q["set"][0]
                        cam.set_job(int(raw) if raw.isdigit() else raw)
                    active, names = cam.jobs()
                    out = {"active": active, "jobs": names}
                elif u.path == "/api/info":
                    mm = cam.get_focus()
                    w, h = cam.fov(mm)
                    active, names = cam.jobs()
                    out = {"mm": mm, "fov_mm": [w, h],
                           "ms": cam.get_shutter(), "gain": cam.get_gain(),
                           "active": active, "jobs": names}
                else:
                    self._reply(404, "text/plain", b"unknown api")
                    return
            out["ok"] = True
            self._reply(200, "application/json", json.dumps(out).encode())
        except (OSError, ValueError, VisorError) as e:
            self._reply(502, "application/json",
                        json.dumps({"ok": False, "error": str(e)}).encode())


def serve(visor_host, visor_port=2006, listen="127.0.0.1", listen_port=8601,
          auto_trigger=True):
    handler = partial(Handler, host=visor_host, port=visor_port,
                      auto_trigger=auto_trigger)
    httpd = ThreadingHTTPServer((listen, listen_port), handler)
    print(f"visordemo web UI: http://{listen}:{listen_port} "
          f"-> VISOR {visor_host}:{visor_port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
