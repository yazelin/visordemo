"""visordemo CLI: snapshot / trigger / serve / simulate."""
import argparse
import sys

from .camera import Camera


def main(argv=None):
    p = argparse.ArgumentParser(prog="visordemo",
                                description="SensoPart VISOR image grabber")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_conn(sp):
        sp.add_argument("--host", default="192.168.2.100", help="VISOR IP")
        sp.add_argument("--port", type=int, default=2006,
                        help="request/response port (default 2006)")

    s = sub.add_parser("snapshot", help="trigger + get image, save as PNG")
    add_conn(s)
    s.add_argument("-o", "--output", default="visor.png")
    s.add_argument("--which", type=int, default=0, choices=(0, 1, 2),
                   help="0=last, 1=last bad, 2=last good image")
    s.add_argument("--no-trigger", action="store_true",
                   help="skip TRG (sensor free-runs)")

    t = sub.add_parser("trigger", help="send TRG only")
    add_conn(t)

    f = sub.add_parser("focus", help="read/set/auto working distance (mm)")
    add_conn(f)
    f.add_argument("mm", nargs="?", type=float, help="set absolute distance in mm")
    f.add_argument("--auto", action="store_true", help="run autofocus")
    f.add_argument("--permanent", action="store_true",
                   help="persist across sensor reboot")

    j = sub.add_parser("job", help="list or switch jobs")
    add_conn(j)
    j.add_argument("job", nargs="?", help="job number or name to switch to")
    j.add_argument("--permanent", action="store_true")

    sh = sub.add_parser("shutter", help="read/set/auto shutter speed (ms)")
    add_conn(sh)
    sh.add_argument("ms", nargs="?", type=float)
    sh.add_argument("--auto", action="store_true")
    sh.add_argument("--permanent", action="store_true")

    g = sub.add_parser("gain", help="read/set gain factor")
    add_conn(g)
    g.add_argument("value", nargs="?", type=float)
    g.add_argument("--permanent", action="store_true")

    i = sub.add_parser("info", help="identity, optics, focus, shutter, gain, FOV")
    add_conn(i)

    v = sub.add_parser("serve", help="web UI preview")
    add_conn(v)
    v.add_argument("--listen", default="127.0.0.1")
    v.add_argument("--listen-port", type=int, default=8601)
    v.add_argument("--no-trigger", action="store_true")

    m = sub.add_parser("simulate", help="run a fake VISOR TCP server")
    m.add_argument("--listen", default="0.0.0.0")
    m.add_argument("--port", type=int, default=2006)

    a = p.parse_args(argv)

    if a.cmd == "snapshot":
        with Camera(a.host, a.port, auto_trigger=not a.no_trigger) as cam:
            frame = cam.capture(a.which)
            with open(a.output, "wb") as f:
                f.write(frame.to_png())
        print(f"{a.output}: {frame.cols}x{frame.rows}, "
              f"type={frame.image_type}, good={frame.good}")
    elif a.cmd == "focus":
        with Camera(a.host, a.port, auto_trigger=False) as cam:
            if a.auto:
                print(f"autofocus -> {cam.autofocus(a.permanent)} mm")
            elif a.mm is not None:
                print(f"set -> {cam.set_focus(a.mm, a.permanent)} mm")
            else:
                print(f"{cam.get_focus()} mm")
    elif a.cmd == "job":
        with Camera(a.host, a.port, auto_trigger=False) as cam:
            if a.job is not None:
                job = int(a.job) if a.job.isdigit() else a.job
                cam.set_job(job, a.permanent)
            active, names = cam.jobs()
        for n, name in enumerate(names, 1):
            print(f"{'*' if n == active else ' '} {n} {name}")
    elif a.cmd == "shutter":
        with Camera(a.host, a.port, auto_trigger=False) as cam:
            if a.auto:
                cam.auto_shutter(a.permanent)
            elif a.ms is not None:
                cam.set_shutter(a.ms, a.permanent)
            print(f"{cam.get_shutter()} ms")
    elif a.cmd == "gain":
        with Camera(a.host, a.port, auto_trigger=False) as cam:
            if a.value is not None:
                cam.set_gain(a.value, a.permanent)
            print(f"{cam.get_gain()}")
    elif a.cmd == "info":
        from .protocol import VisorError
        with Camera(a.host, a.port, auto_trigger=False) as cam:
            try:
                print("identity:", cam.identity())
            except VisorError:
                print("identity: (GSI not supported by this firmware)")
            p = cam.internal_params()
            mm = cam.get_focus()
            w, h = cam.fov(mm)
            active, names = cam.jobs()
            print(f"optics: focal {p['focal_mm']}mm, pixel {p['pitch_x_um']}um, "
                  f"{p['width_px']}x{p['height_px']}px")
            print(f"focus: {mm} mm  -> FOV {w} x {h} mm")
            print(f"shutter: {cam.get_shutter()} ms, gain: {cam.get_gain()}")
            print(f"jobs: {[(n, name) for n, name in enumerate(names, 1)]}, "
                  f"active={active}")
    elif a.cmd == "trigger":
        with Camera(a.host, a.port, auto_trigger=False) as cam:
            ok = cam.trigger()
        print("TRG:", "Pass" if ok else "Fail")
        sys.exit(0 if ok else 1)
    elif a.cmd == "serve":
        from .server import serve
        serve(a.host, a.port, a.listen, a.listen_port,
              auto_trigger=not a.no_trigger)
    elif a.cmd == "simulate":
        from .simulator import main as sim_main
        sim_main(a.listen, a.port)


if __name__ == "__main__":
    main()
