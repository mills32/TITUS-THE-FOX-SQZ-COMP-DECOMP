#!/usr/bin/env python3
"""
SQZ LZW codec with EGA plane BMP conversion.
Original LZW algorithm by Jesses (mail at ttf dot mine dot nu) - http://ttf.mine.nu

Usage:
    Decompress SQZ to BMP:   python sqz_lzw.py d INPUT.SQZ OUTPUT.BMP
    Compress BMP to SQZ:     python sqz_lzw.py c INPUT.BMP  OUTPUT.SQZ
    Compress BMP + altlzw:   python sqz_lzw.py c -altlzw INPUT.BMP OUTPUT.SQZ

    Raw (no BMP conversion):
    Decompress SQZ to BIN:   python sqz_lzw.py d -raw INPUT.SQZ OUTPUT.BIN
    Compress BIN to SQZ:     python sqz_lzw.py c -raw INPUT.BIN  OUTPUT.SQZ

BMP input for compression: 16-color 4bpp OR 256-color 8bpp indexed BMP, any size
that is a multiple of 8 pixels wide.  Only the first 16 palette entries are used.
Palette indices are mapped to EGA colors by nearest-color match.

BMP output from decompression: 16-color 4bpp indexed BMP with the standard EGA
palette.  Rows are stored bottom-to-top (standard BMP convention).

Binary (BIN) format inside the SQZ:
    4 sequential planes of (width * height / 8) bytes each.
    Plane 0 carries bit 0 of every pixel's EGA color index.
    Plane 1 carries bit 1, plane 2 carries bit 2, plane 3 carries bit 3.
    Within each plane, pixels are ordered left-to-right, top-to-bottom,
    MSB of each byte = leftmost pixel (standard EGA bit-plane layout).
"""

import struct
import sys


# ---------------------------------------------------------------------------
# EGA default palette  (16 entries, each (R, G, B))
# ---------------------------------------------------------------------------

EGA_PALETTE: list[tuple[int, int, int]] = [
    (0x00, 0x00, 0x00),  #  0  black
    (0x00, 0x00, 0xAA),  #  1  blue
    (0x00, 0xAA, 0x00),  #  2  green
    (0x00, 0xAA, 0xAA),  #  3  cyan
    (0xAA, 0x00, 0x00),  #  4  red
    (0xAA, 0x00, 0xAA),  #  5  magenta
    (0xAA, 0x55, 0x00),  #  6  brown
    (0xAA, 0xAA, 0xAA),  #  7  light gray
    (0x55, 0x55, 0x55),  #  8  dark gray
    (0x55, 0x55, 0xFF),  #  9  light blue
    (0x55, 0xFF, 0x55),  # 10  light green
    (0x55, 0xFF, 0xFF),  # 11  light cyan
    (0xFF, 0x55, 0x55),  # 12  light red
    (0xFF, 0x55, 0xFF),  # 13  light magenta
    (0xFF, 0xFF, 0x55),  # 14  yellow
    (0xFF, 0xFF, 0xFF),  # 15  white
]


# ---------------------------------------------------------------------------
# LZW constants
# ---------------------------------------------------------------------------

CLEAR_CODE = 0x100
END_CODE   = 0x101
FIRST      = 0x102
MAX_TABLE  = 0x1000


# ---------------------------------------------------------------------------
# BMP reading
# ---------------------------------------------------------------------------

def read_bmp(path: str) -> tuple[int, int, list[int]]:
    """
    Read an indexed-colour BMP (4bpp or 8bpp) and return
    (width, height, pixels) where pixels is a flat list of palette indices
    in top-to-bottom, left-to-right order.

    BMPs store rows bottom-to-top; this function inverts them so row 0 is
    the top of the image, matching the EGA plane layout expected by the game.

    Palette indices are remapped to EGA colour indices 0-15 using a
    nearest-colour (Euclidean RGB distance) match against EGA_PALETTE so that
    any 16- or 256-colour BMP with EGA-like colours is handled correctly.
    """
    with open(path, "rb") as f:
        data = f.read()

    # --- File header ---
    if data[:2] != b"BM":
        raise ValueError("Not a BMP file")
    pixel_offset = struct.unpack_from("<I", data, 10)[0]

    # --- DIB header ---
    dib_size = struct.unpack_from("<I", data, 14)[0]
    if dib_size < 40:
        raise ValueError(f"Unsupported DIB header size {dib_size}")
    width   = struct.unpack_from("<i", data, 18)[0]
    height  = struct.unpack_from("<i", data, 22)[0]
    bpp     = struct.unpack_from("<H", data, 28)[0]
    compress = struct.unpack_from("<I", data, 30)[0]

    if bpp not in (4, 8):
        raise ValueError(f"BMP must be 4bpp or 8bpp indexed, got {bpp}bpp")
    if compress != 0:
        raise ValueError(f"Compressed BMPs are not supported (compression={compress})")

    bottom_up = True
    if height < 0:
        height    = -height
        bottom_up = False

    # --- Palette ---
    pal_entry_count = struct.unpack_from("<I", data, 46)[0]
    if pal_entry_count == 0:
        pal_entry_count = 2 ** bpp
    pal_start = 14 + dib_size
    bmp_palette: list[tuple[int, int, int]] = []
    for i in range(pal_entry_count):
        b, g, r, _ = data[pal_start + i*4 : pal_start + i*4 + 4]
        bmp_palette.append((r, g, b))

    # Build a lookup: BMP palette index → nearest EGA index
    def nearest_ega(r: int, g: int, b: int) -> int:
        best, best_d = 0, 10**9
        for ei, (er, eg, eb) in enumerate(EGA_PALETTE):
            d = (r-er)**2 + (g-eg)**2 + (b-eb)**2
            if d < best_d:
                best_d, best = d, ei
        return best

    ega_map = [nearest_ega(*rgb) for rgb in bmp_palette]

    # --- Pixel data ---
    if bpp == 4:
        row_stride = (width // 2 + 3) & ~3   # rows padded to 4 bytes
    else:
        row_stride = (width + 3) & ~3

    rows: list[list[int]] = []
    for row_idx in range(height):
        row_start = pixel_offset + row_idx * row_stride
        row_pixels: list[int] = []
        if bpp == 4:
            for byte_idx in range((width + 1) // 2):
                byte = data[row_start + byte_idx]
                row_pixels.append(byte >> 4)          # high nibble = left pixel
                if len(row_pixels) < width:
                    row_pixels.append(byte & 0x0F)    # low nibble  = right pixel
        else:  # 8bpp
            for byte_idx in range(width):
                row_pixels.append(data[row_start + byte_idx])
        rows.append(row_pixels)

    if bottom_up:
        rows.reverse()   # now row 0 = top of image

    # Remap every pixel to an EGA index
    pixels = [ega_map[p] for row in rows for p in row]
    return width, height, pixels


# ---------------------------------------------------------------------------
# BMP writing  (4bpp, 16-colour, EGA palette, bottom-to-top rows)
# ---------------------------------------------------------------------------

def write_bmp(path: str, width: int, height: int, pixels: list[int]) -> None:
    """
    Write a 4bpp indexed BMP using the standard EGA palette.
    pixels must be a flat top-to-bottom list of EGA colour indices (0-15).
    Rows are reversed to bottom-to-top as required by the BMP specification.
    """
    row_stride    = (width // 2 + 3) & ~3
    pixel_data_sz = row_stride * height
    palette_sz    = 16 * 4
    header_sz     = 14 + 40 + palette_sz
    file_sz       = header_sz + pixel_data_sz

    buf = bytearray()

    # BMP file header
    buf += b"BM"
    buf += struct.pack("<I", file_sz)
    buf += struct.pack("<HH", 0, 0)
    buf += struct.pack("<I", header_sz)

    # BITMAPINFOHEADER
    buf += struct.pack("<I", 40)
    buf += struct.pack("<i", width)
    buf += struct.pack("<i", height)      # positive = bottom-to-top storage
    buf += struct.pack("<H", 1)           # colour planes
    buf += struct.pack("<H", 4)           # bits per pixel
    buf += struct.pack("<I", 0)           # no compression
    buf += struct.pack("<I", pixel_data_sz)
    buf += struct.pack("<i", 2835) * 2    # ~72 dpi
    buf += struct.pack("<I", 16)          # colours used
    buf += struct.pack("<I", 0)           # important colours

    # Palette in BMP order (BGR0)
    for r, g, b in EGA_PALETTE:
        buf += bytes([b, g, r, 0])

    # Pixel rows stored bottom-to-top
    for row in range(height - 1, -1, -1):
        row_buf = bytearray(row_stride)
        for col in range(width):
            idx = pixels[row * width + col] & 0x0F
            if col % 2 == 0:
                row_buf[col // 2] = idx << 4
            else:
                row_buf[col // 2] |= idx
        buf += row_buf

    with open(path, "wb") as f:
        f.write(buf)


# ---------------------------------------------------------------------------
# EGA plane packing / unpacking
# ---------------------------------------------------------------------------

def pixels_to_planes(width: int, height: int, pixels: list[int]) -> bytes:
    """
    Convert a flat list of EGA colour indices (top-to-bottom, left-to-right)
    into the 4-plane binary format used by the SQZ payload.

    Layout: [plane0 | plane1 | plane2 | plane3]
    Each plane is (width * height / 8) bytes, MSB = leftmost pixel in each byte.
    Plane p contains bit p of every pixel's colour index.
    """
    if width % 8 != 0:
        raise ValueError(f"Width must be a multiple of 8, got {width}")

    bytes_per_row = width // 8
    plane_size    = bytes_per_row * height
    planes        = [bytearray(plane_size) for _ in range(4)]

    for i, color in enumerate(pixels):
        row      = i // width
        col      = i %  width
        byte_idx = row * bytes_per_row + col // 8
        bit_idx  = 7 - (col % 8)           # MSB = leftmost pixel
        for p in range(4):
            if (color >> p) & 1:
                planes[p][byte_idx] |= (1 << bit_idx)

    return b"".join(bytes(pl) for pl in planes)


def planes_to_pixels(width: int, height: int, raw: bytes) -> list[int]:
    """
    Convert the 4-plane binary payload back to a flat pixel list.
    Inverse of pixels_to_planes.
    """
    if width % 8 != 0:
        raise ValueError(f"Width must be a multiple of 8, got {width}")

    bytes_per_row = width // 8
    plane_size    = bytes_per_row * height
    if len(raw) < plane_size * 4:
        raise ValueError(
            f"Raw data too short: need {plane_size * 4} bytes, got {len(raw)}"
        )

    planes = [raw[p * plane_size : (p + 1) * plane_size] for p in range(4)]
    pixels = []

    for row in range(height):
        for col in range(width):
            byte_idx = row * bytes_per_row + col // 8
            bit_idx  = 7 - (col % 8)
            color    = 0
            for p in range(4):
                if (planes[p][byte_idx] >> bit_idx) & 1:
                    color |= (1 << p)
            pixels.append(color)

    return pixels


# ---------------------------------------------------------------------------
# LZW decompression
# ---------------------------------------------------------------------------

def decompress(data: bytes, altlzw: bool = False) -> bytes:
    """Decompress a raw SQZ-LZW bitstream (header already stripped)."""

    clear_code = CLEAR_CODE
    end_code   = END_CODE
    if altlzw:
        clear_code, end_code = END_CODE, CLEAR_CODE

    pos = 0

    def next_byte() -> int:
        nonlocal pos
        if pos < len(data):
            b = data[pos]; pos += 1; return b
        return 0

    buf24  = (next_byte() << 16) | (next_byte() << 8) | next_byte()
    bitpos = 0

    def read_code(nbit: int) -> int:
        nonlocal buf24, bitpos
        bitpos += nbit
        cw     = (buf24 >> (24 - bitpos)) & ((1 << nbit) - 1)
        buf24  = ((buf24 << 8) | next_byte()) & 0xFFFFFF
        if bitpos >= 16:
            buf24 = ((buf24 << 8) | next_byte()) & 0xFFFFFF
        bitpos &= 7
        return cw

    dict_entries: list[tuple[int, int, int]] = []
    dictsize = FIRST

    def decode_string(cw: int) -> bytes:
        result = []
        while cw >= FIRST:
            prefix, byte = dict_entries[cw - FIRST][0], dict_entries[cw - FIRST][1]
            result.append(byte)
            cw = prefix
        result.append(cw)
        result.reverse()
        return bytes(result)

    output = bytearray()
    nbit   = 9
    prev   = clear_code

    while prev != end_code:
        if prev == clear_code:
            nbit = 9
            dictsize = FIRST
            dict_entries.clear()

        cw = read_code(nbit)

        if cw != clear_code and cw != end_code:
            if cw < dictsize:
                first = cw if cw < FIRST else dict_entries[cw - FIRST][2]
            else:
                if prev == clear_code:
                    raise ValueError("Unexpected codeword after CLEAR")
                if cw != dictsize:
                    raise ValueError(f"cw ({cw}) != dictsize ({dictsize})")
                first = prev if prev < FIRST else dict_entries[prev - FIRST][2]

            if prev != clear_code and dictsize < MAX_TABLE:
                pfirst = prev if prev < FIRST else dict_entries[prev - FIRST][2]
                dict_entries.append((prev, first, pfirst))
                dictsize += 1
                if dictsize == (1 << nbit) and nbit < 12:
                    nbit += 1

            output.extend(decode_string(cw))

        prev = cw

    return bytes(output)


# ---------------------------------------------------------------------------
# LZW compression
# ---------------------------------------------------------------------------

def compress(data: bytes, altlzw: bool = False) -> bytes:
    """
    Compress bytes to the SQZ-LZW bitstream format.

    Key design points mirroring the decompressor:

    No initial CLEAR code: the original SQZ compressor never emits one.
    The decompressor initialises prev = CLEAR_CODE before the first read, so
    it is already in the reset state.  An explicit leading CLEAR would shift
    every byte by 9 bits and corrupt files read by the game.

    Two dictsize/nbit counters: the encoder adds one entry per *miss*; the
    decoder adds one entry per *codeword read*.  They grow at different rates
    on repetitive data.  dec_dictsize/dec_nbit simulate the decoder's counter
    so every codeword is written at the width the decoder expects.

    Table-full CLEAR: when dec_dictsize reaches MAX_TABLE the decoder stops
    adding entries; the encoder emits CLEAR and both sides reset together.
    """

    clear_code = CLEAR_CODE
    end_code   = END_CODE
    if altlzw:
        clear_code, end_code = END_CODE, CLEAR_CODE

    # Bit-writer (MSB-first, matches the decompressor's 24-bit sliding reader)
    out_bits:  bytearray = bytearray()
    bit_buf:   int       = 0
    bits_used: int       = 0

    def write_code(code: int, nb: int) -> None:
        nonlocal bit_buf, bits_used
        bit_buf    = (bit_buf << nb) | code
        bits_used += nb
        while bits_used >= 8:
            bits_used -= 8
            out_bits.append((bit_buf >> bits_used) & 0xFF)

    def flush_bits() -> None:
        nonlocal bit_buf, bits_used
        if bits_used > 0:
            out_bits.append((bit_buf << (8 - bits_used)) & 0xFF)
            bits_used = 0
            bit_buf   = 0

    # Encoder string table: (prefix_codeword, ext_byte) → new codeword
    enc_table:    dict[tuple[int, int], int] = {}
    first_byte:   dict[int, int]             = {i: i for i in range(256)}
    enc_dictsize: int                        = FIRST

    # Decoder simulation counters
    dec_dictsize:   int  = FIRST
    dec_nbit:       int  = 9
    dec_prev_clear: bool = True

    def reset() -> None:
        nonlocal enc_dictsize, dec_dictsize, dec_nbit, dec_prev_clear
        enc_table.clear()
        first_byte.clear()
        first_byte.update({i: i for i in range(256)})
        enc_dictsize   = FIRST
        dec_dictsize   = FIRST
        dec_nbit       = 9
        dec_prev_clear = True

    def enc_add(w_code: int, ext_byte: int) -> None:
        nonlocal enc_dictsize
        if enc_dictsize >= MAX_TABLE:
            return
        enc_table[(w_code, ext_byte)] = enc_dictsize
        first_byte[enc_dictsize]      = first_byte[w_code]
        enc_dictsize += 1

    def dec_advance() -> None:
        nonlocal dec_dictsize, dec_nbit, dec_prev_clear
        if dec_prev_clear:
            dec_prev_clear = False
            return
        if dec_dictsize < MAX_TABLE:
            dec_dictsize += 1
            if dec_dictsize == (1 << dec_nbit) and dec_nbit < 12:
                dec_nbit += 1

    if not data:
        write_code(end_code, dec_nbit)
        flush_bits()
        return bytes(out_bits)

    w_code: int = data[0]

    for b in data[1:]:
        if (w_code, b) in enc_table:
            w_code = enc_table[(w_code, b)]
        else:
            write_code(w_code, dec_nbit)
            dec_advance()

            if dec_dictsize >= MAX_TABLE:
                write_code(clear_code, dec_nbit)
                reset()
                w_code = b
                continue

            enc_add(w_code, b)
            w_code = b

    write_code(w_code, dec_nbit)
    dec_advance()
    write_code(end_code, dec_nbit)
    flush_bits()

    return bytes(out_bits)


# ---------------------------------------------------------------------------
# SQZ file I/O  (header + LZW stream)
# ---------------------------------------------------------------------------

def _read_sqz(path: str) -> tuple[int, bytes]:
    """Return (uncompressed_size, raw_lzw_stream)."""
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) < 4:
        raise ValueError("File too short to be a valid SQZ file")
    unpsize = (raw[0] << 16) | raw[2] | (raw[3] << 8)
    fmt     = raw[1]
    if fmt != 0x10:
        raise ValueError(
            f"Byte 1 is 0x{fmt:02X}, not 0x10 — may be a Huffman-encoded file"
        )
    return unpsize, raw[4:]


def _write_sqz(path: str, payload: bytes, altlzw: bool = False) -> None:
    """Compress payload and write a complete SQZ file."""
    unpsize    = len(payload)
    compressed = compress(payload, altlzw=altlzw)
    header = bytes([
        (unpsize >> 16) & 0xFF,
        0x10,
        unpsize        & 0xFF,
        (unpsize >> 8) & 0xFF,
    ])
    with open(path, "wb") as f:
        f.write(header + compressed)
    total = 4 + len(compressed)
    ratio = total / unpsize * 100 if unpsize else 0
    print(f"Compressed {unpsize} -> {total} bytes ({ratio:.1f}%)", file=sys.stderr)


# ---------------------------------------------------------------------------
# High-level file operations
# ---------------------------------------------------------------------------

# Default image dimensions used when no other information is available.
# The EGA screen is always 320 x 200; this can be overridden via the -size flag.
DEFAULT_WIDTH  = 320
DEFAULT_HEIGHT = 200


def decompress_to_bmp(sqz_path: str, bmp_path: str,
                      width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT,
                      altlzw: bool = False) -> None:
    """Decompress a SQZ file and write the result as a 16-colour EGA BMP."""
    unpsize, stream = _read_sqz(sqz_path)
    raw    = decompress(stream, altlzw=altlzw)
    if len(raw) != unpsize:
        print(
            f"Warning: expected {unpsize} bytes, got {len(raw)}", file=sys.stderr
        )
    pixels = planes_to_pixels(width, height, raw)
    write_bmp(bmp_path, width, height, pixels)
    print(
        f"Decompressed {unpsize} bytes -> {width}x{height} BMP", file=sys.stderr
    )


def compress_from_bmp(bmp_path: str, sqz_path: str, altlzw: bool = False) -> None:
    """Read an indexed BMP, convert to EGA planes, and write a SQZ file."""
    width, height, pixels = read_bmp(bmp_path)
    if width % 8 != 0:
        raise ValueError(f"Image width {width} is not a multiple of 8")
    raw = pixels_to_planes(width, height, pixels)
    _write_sqz(sqz_path, raw, altlzw=altlzw)
    print(
        f"Compressed {width}x{height} BMP ({len(raw)} bytes payload)", file=sys.stderr
    )


def decompress_raw(sqz_path: str, bin_path: str, altlzw: bool = False) -> None:
    """Decompress a SQZ file to a raw binary (no BMP conversion)."""
    unpsize, stream = _read_sqz(sqz_path)
    raw = decompress(stream, altlzw=altlzw)
    if len(raw) != unpsize:
        print(
            f"Warning: expected {unpsize} bytes, got {len(raw)}", file=sys.stderr
        )
    with open(bin_path, "wb") as f:
        f.write(raw)
    print(f"Decompressed {len(raw)} bytes", file=sys.stderr)


def compress_raw(bin_path: str, sqz_path: str, altlzw: bool = False) -> None:
    """Compress a raw binary to SQZ (no BMP conversion)."""
    with open(bin_path, "rb") as f:
        data = f.read()
    _write_sqz(sqz_path, data, altlzw=altlzw)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def usage() -> None:
    print(__doc__, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    args = sys.argv[1:]

    if len(args) < 3:
        usage()

    mode   = args[0].lower()
    altlzw = "-altlzw" in args
    raw    = "-raw"    in args
    flags  = {a for a in args if a.startswith("-")}
    posargs = [a for a in args if not a.startswith("-")]

    # Parse optional -size WxH flag
    width, height = DEFAULT_WIDTH, DEFAULT_HEIGHT
    for a in args:
        if a.startswith("-size="):
            try:
                w, h = a[6:].split("x")
                width, height = int(w), int(h)
            except Exception:
                print(f"Bad -size flag: {a}", file=sys.stderr)
                usage()

    if len(posargs) < 3:
        usage()

    in_p  = posargs[1]
    out_p = posargs[2]

    if mode == "d":
        if raw:
            decompress_raw(in_p, out_p, altlzw=altlzw)
        else:
            decompress_to_bmp(in_p, out_p, width=width, height=height, altlzw=altlzw)
    elif mode == "c":
        if raw:
            compress_raw(in_p, out_p, altlzw=altlzw)
        else:
            compress_from_bmp(in_p, out_p, altlzw=altlzw)
    else:
        usage()
