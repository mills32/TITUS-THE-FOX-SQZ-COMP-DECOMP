#!/usr/bin/env python3
"""
patch_exe.py

Replace EGA palette indexes in TITUS.EXE (10 Great Games CDROM by Telstar Fun and Games).

Usage:
    python patch_exe.py TITUS.EXE
"""

import sys
import shutil
from pathlib import Path

# ── Patch configuration ──────────────────────────────────────────────────────
#Levels palette
PATCH_OFFSET_0 = 0xBBCB
#Font palette
PATCH_OFFSET_1 = 0x708A

#Custom palettes
PALETTE_LEVELS_EGA_ORIGINAL = bytes([ 0,23, 0, 4, 6, 5,20,22,16,21, 7,17, 3,19, 2,17])
PALETTE_FONTS_EGA_ORIGINAL  = bytes([ 0, 0, 0, 0, 0,19,19,19, 3, 3, 3, 3, 3, 3, 3, 3])
PALETTE_LEVELS_EGA_DEFAULT  = bytes([ 0,23, 0,16, 4, 6,20,22,16, 7,23,17, 3,19,16, 1])
PALETTE_FONTS_EGA_DEFAULT   = bytes([ 0, 0, 0, 0, 0,23,22,22, 7,20,20,20, 6, 6, 4, 4])
PALETTE_LEVELS_EGA_EXTENDED = bytes([ 0,63, 0,56,20,52,38,54,32,56, 7,25,11,27,48, 9])
PALETTE_FONTS_EGA_EXTENDED  = bytes([ 0, 0, 0, 0, 0,63,54,46,60,52,36,36,36, 4, 4,32])

pal0 = PALETTE_LEVELS_EGA_ORIGINAL;
pal1 = PALETTE_FONTS_EGA_ORIGINAL;

# ─────────────────────────────────────────────────────────────────────────────

def fmt(b: bytes) -> str:
    """Format a bytes object as uppercase hex pairs."""
    return " ".join(f"{x:02X}" for x in b)


def choose_palette() -> bytes:
    print("Select EGA mode:\n")
    print(f" - 0 Restore original file data.")
    print(f" - 1 EGA default: reorganized palette from default EGA 16 colors).")
    print(f" - 2 EGA extended: 16 colors from extended 64 color palette, (requires EGA monitor / or VGA output like in some emulators/clones/fpgas).")
    print()

    while True:
        global pal0
        global pal1
        choice = input("Enter 0, 1 or 2: ").strip()
        if choice == "0":
            print("Restore original palette")
            pal0 = PALETTE_LEVELS_EGA_ORIGINAL
            pal1 = PALETTE_FONTS_EGA_ORIGINAL
            return 0
        elif choice == "1":
            print("Using EGA default")
            pal0 = PALETTE_LEVELS_EGA_DEFAULT
            pal1 = PALETTE_FONTS_EGA_DEFAULT
            return 0
        elif choice == "2":
            print("Using EGA extended")
            pal0 = PALETTE_LEVELS_EGA_EXTENDED
            pal1 = PALETTE_FONTS_EGA_EXTENDED
            return 0
        else:
            print("    Invalid choice — please enter 1 or 2.")


def patch_file(target: Path) -> None:
    if not target.is_file():
        raise FileNotFoundError(f"Target file not found: {target}")

    file_size = target.stat().st_size
    if PATCH_OFFSET_0 + 16 > file_size:
        raise ValueError(
            f"Patch region 0x{PATCH_OFFSET_0:X}–0x{PATCH_OFFSET_0 + 16 - 1:X} "
            f"extends beyond file size 0x{file_size:X} ({file_size} bytes)."
        )
    if PATCH_OFFSET_1 + 16 > file_size:
        raise ValueError(
            f"Patch region 0x{PATCH_OFFSET_1:X}–0x{PATCH_OFFSET_1 + 16 - 1:X} "
            f"extends beyond file size 0x{file_size:X} ({file_size} bytes)."
        )

    # Back up the original
    backup = target.with_suffix(target.suffix + ".orig")
    shutil.copy2(target, backup)
    print(f"Backup written : {backup}")

    # Patch in-place
    with open(target, "r+b") as fh:
        fh.seek(PATCH_OFFSET_0)
        fh.write(pal0)
        fh.seek(PATCH_OFFSET_1)
        fh.write(pal1)

    print(f"Patch applied  : {target}")


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: python {Path(__file__).name} <target_file>")
        sys.exit(1)

    target = Path(sys.argv[1])

    try:
        choose_palette()
        print()
        patch_file(target)
    except (ValueError, FileNotFoundError) as exc:
        print(f"\n[!] Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
