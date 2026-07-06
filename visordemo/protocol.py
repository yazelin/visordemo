"""SensoPart VISOR ASCII telegram protocol (port 2006, request/response).

依據官方 VISOR Communications Manual 068-14859-05 EN (2024-04-08):
- TRG  -> "TRGP" / "TRGF"
- GIMx -> 15-byte header + optional EOT + rows*cols raw 8-bit image data
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
        # ponytail: Bayer 也直接當灰階輸出 raw mosaic;需要彩色時再加 demosaic
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


def png_gray(rows: int, cols: int, data: bytes) -> bytes:
    """Encode raw 8-bit grayscale pixels as PNG. Pure stdlib (zlib)."""
    if len(data) != rows * cols:
        raise ValueError(f"expected {rows * cols} bytes, got {len(data)}")

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body)))

    ihdr = struct.pack(">IIBBBBB", cols, rows, 8, 0, 0, 0, 0)  # 8-bit grayscale
    raw = b"".join(b"\x00" + data[r * cols:(r + 1) * cols] for r in range(rows))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
