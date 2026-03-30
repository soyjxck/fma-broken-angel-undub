#!/usr/bin/env python3
"""
FMA Undub Patch — Simple Python Applicator
===========================================

Applies the undub patch to a USA ISO of Fullmetal Alchemist and the Broken Angel.

Usage:
    python3 apply_patch.py "Fullmetal Alchemist and the Broken Angel (USA).iso"

Requires xdelta3 installed (brew install xdelta / apt install xdelta3).
"""

import sys
import os
import subprocess
import hashlib
import shutil


PATCH_FILE = "FMA_Undub.xdelta"
EXPECTED_SIZE = 1_927_217_152


def find_xdelta():
    """Find xdelta3 binary."""
    for name in ["xdelta3", "xdelta"]:
        path = shutil.which(name)
        if path:
            return path
        # Check homebrew
        for prefix in ["/opt/homebrew/bin", "/usr/local/bin"]:
            full = os.path.join(prefix, name)
            if os.path.exists(full):
                return full
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    iso_path = sys.argv[1]
    patch_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), PATCH_FILE)
    output_path = os.path.join(os.path.dirname(iso_path), "FMA_Undub.iso")

    # Validate inputs
    if not os.path.exists(iso_path):
        print(f"ERROR: ISO not found: {iso_path}")
        sys.exit(1)

    if not os.path.exists(patch_path):
        print(f"ERROR: Patch file not found: {patch_path}")
        print(f"  Expected at: {patch_path}")
        sys.exit(1)

    # Check ISO size
    iso_size = os.path.getsize(iso_path)
    if iso_size != EXPECTED_SIZE:
        print(f"WARNING: ISO size mismatch!")
        print(f"  Expected: {EXPECTED_SIZE:,} bytes")
        print(f"  Got:      {iso_size:,} bytes")
        print(f"  Make sure this is the USA version (SLUS-20994)")
        response = input("  Continue anyway? [y/N] ")
        if response.lower() != "y":
            sys.exit(1)

    # Find xdelta3
    xdelta = find_xdelta()
    if not xdelta:
        print("ERROR: xdelta3 not found!")
        print("  Install it:")
        print("    macOS:   brew install xdelta")
        print("    Linux:   apt install xdelta3")
        print("    Windows: https://github.com/jmacd/xdelta-gpl/releases")
        sys.exit(1)

    print(f"Fullmetal Alchemist — Undub Patch")
    print(f"=" * 40)
    print(f"  Source: {os.path.basename(iso_path)}")
    print(f"  Patch:  {os.path.basename(patch_path)}")
    print(f"  Output: {os.path.basename(output_path)}")
    print()

    if os.path.exists(output_path):
        print(f"  Output already exists, will overwrite.")

    print("  Applying patch (this may take a minute)...")

    result = subprocess.run(
        [xdelta, "-d", "-s", iso_path, patch_path, output_path],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"  ERROR: Patching failed!")
        print(f"  {result.stderr}")
        sys.exit(1)

    output_size = os.path.getsize(output_path)
    print(f"  Done!")
    print(f"  Output: {output_path}")
    print(f"  Size:   {output_size:,} bytes")
    print()
    print(f"  Load FMA_Undub.iso in PCSX2 to play!")


if __name__ == "__main__":
    main()
