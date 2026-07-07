"""SensoPart VISOR ASCII telegram protocol (port 2006, request/response).

依據官方 VISOR Communications Manual 068-14859-05 EN (2024-04-08):
- TRG  -> "TRGP" / "TRGF"
- GIMx -> 15-byte header + optional EOT + rows*cols raw 8-bit image data
- GFC / SFC / AFC -> 讀 / 設 / 自動對焦(工作距離,僅電動對焦機種)
"""
from dataclasses import dataclass
import struct
import zlib

IMAGE_TYPES = {0: "grayscale", 3: "bayer_bg"}


class VisorError(Exception):
    pass


@dataclass
class Frame:
    rows: int
    cols: int
    image_type: int   # 0=grayscale, 3=Bayer BG
    good: bool        # image result: good/failed image
    data: bytes       # raw 8-bit pixels, rows*cols

    def to_png(self) -> bytes:
        if self.image_type == 3:
            r, c, rgb = demosaic_half(self.rows, self.cols, self.data)
            return png_rgb(r, c, rgb)
        return png_gray(self.rows, self.cols, self.data)


def trg_request() -> bytes:
    return b"TRG"


def parse_trg_response(resp: bytes) -> bool:
    """4 bytes: TRGP / TRGF -> True on Pass."""
    if len(resp) != 4 or resp[:3] != b"TRG" or resp[3:4] not in (b"P", b"F"):
        raise VisorError(f"malformed TRG response: {resp!r}")
    return resp[3:4] == b"P"


def gim_request(which: int = 0) -> bytes:
    """which: 0=last image, 1=last bad image, 2=last good image."""
    if which not in (0, 1, 2):
        raise ValueError("which must be 0, 1 or 2")
    return b"GIM" + str(which).encode()


def parse_gim_header(header: bytes) -> tuple[int, int, int, bool]:
    """15-byte header -> (rows, cols, image_type, good). Raises on Fail."""
    if len(header) != 15 or header[:3] != b"GIM":
        raise VisorError(f"malformed GIM header: {header!r}")
    if header[3:4] == b"F":
        raise VisorError(f"GIM failed, error code {header[4:5].decode(errors='replace')}")
    if header[3:4] != b"P":
        raise VisorError(f"malformed GIM header: {header!r}")
    image_type = int(header[5:6])
    good = header[6:7] == b"1"
    rows = int(header[7:11])
    cols = int(header[11:15])
    return rows, cols, image_type, good


def gfc_request() -> bytes:
    """Read working distance, unit 1/1000 mm."""
    return b"GFC10"


def sfc_request(mm: float, permanent: bool = False) -> bytes:
    """Set working distance (absolute, mm)."""
    return (b"SFC1" + (b"1" if permanent else b"0") + b"0" + b"0"
            + f"{round(mm * 1000):08d}".encode())


def afc_request(permanent: bool = False) -> bytes:
    """Auto focus: step size 3, highest score, mm, default range."""
    return b"AFC1" + (b"1" if permanent else b"0") + b"3" + b"000" + b"0" + b"0"


def parse_focus_response(resp: bytes, cmd: bytes) -> float:
    """GFCP/SFCP/AFCP + 3 error digits + 8-digit distance (mm*1000) -> mm."""
    if len(resp) < 15 or resp[:3] != cmd:
        raise VisorError(f"malformed {cmd.decode()} response: {resp!r}")
    if resp[3:4] != b"P":
        raise VisorError(
            f"{cmd.decode()} failed, error code {resp[4:7].decode(errors='replace')}"
            " (manual focus model?)")
    return int(resp[7:15]) / 1000


def _png(rows: int, cols: int, color_type: int, raw: bytes) -> bytes:
    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body)))

    ihdr = struct.pack(">IIBBBBB", cols, rows, 8, color_type, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def png_gray(rows: int, cols: int, data: bytes) -> bytes:
    """Encode raw 8-bit grayscale pixels as PNG. Pure stdlib (zlib)."""
    if len(data) != rows * cols:
        raise ValueError(f"expected {rows * cols} bytes, got {len(data)}")
    raw = b"".join(b"\x00" + data[r * cols:(r + 1) * cols] for r in range(rows))
    return _png(rows, cols, 0, raw)


def png_rgb(rows: int, cols: int, rgb: bytes) -> bytes:
    """Encode raw 8-bit RGBRGB... pixels as PNG."""
    if len(rgb) != rows * cols * 3:
        raise ValueError(f"expected {rows * cols * 3} bytes, got {len(rgb)}")
    stride = cols * 3
    raw = b"".join(b"\x00" + rgb[r * stride:(r + 1) * stride] for r in range(rows))
    return _png(rows, cols, 2, raw)


def demosaic_half(rows: int, cols: int, data: bytes):
    """Bayer BG mosaic -> half-resolution RGB. Returns (rows//2, cols//2, rgb).

    每個 2x2 quad(B G / G R)出一個 RGB 像素。
    # ponytail: 半解析度最簡 demosaic;需要全解析度彩色再上內插
    """
    out_r, out_c = rows // 2, cols // 2
    rgb = bytearray(out_r * out_c * 3)
    for r in range(out_r):
        top = data[2 * r * cols:(2 * r + 1) * cols]
        bot = data[(2 * r + 1) * cols:(2 * r + 2) * cols]
        row_off = r * out_c * 3
        for c in range(out_c):
            i = row_off + c * 3
            rgb[i] = bot[2 * c + 1]                          # R
            rgb[i + 1] = (top[2 * c + 1] + bot[2 * c]) >> 1  # G avg
            rgb[i + 2] = top[2 * c]                          # B
    return out_r, out_c, bytes(rgb)
