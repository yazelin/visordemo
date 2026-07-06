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
