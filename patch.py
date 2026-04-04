#!/usr/bin/env python3
"""
FMA Undub Patcher
==================

Three ways to create the undubbed ISO:

  1) Full pipeline (both ISOs + auto-builds ffmpeg + burns subtitles):
     python3 patch.py full <usa_iso> <jp_iso> [output_iso]

  2) Audio-only (both ISOs, no subs, no ffmpeg needed):
     python3 patch.py audio <usa_iso> <jp_iso> [output_iso]

  3) Apply xdelta patch (USA ISO + xdelta file):
     python3 patch.py xdelta <usa_iso> <xdelta_file> [output_iso]

Options:
    --generate-xdelta   Also create an xdelta patch file after patching
    --skip-verify       Skip MD5 hash verification
    --dump-mkv <dir>    Export subtitled cutscenes as MKV files to <dir>
"""

import struct
import os
import sys
import shutil
import subprocess
import tempfile

from lib.constants import (
    DSI_BLOCK_SIZE, SECTOR, EXPECTED_HASHES,
    DSI_NAMES, SUBS_DIR,
)
from lib.iso import find_file_in_iso, update_dir_entry, verify_iso
from lib.cddata import build_mapping, patch_cddata
from lib.video import build_subtitled_dsi, dump_mkv
from lib.ffmpeg import find_or_build_ffmpeg


# =============================================================================
# xdelta
# =============================================================================

def find_xdelta():
    """Find xdelta3 binary."""
    xdelta = shutil.which('xdelta3') or shutil.which('xdelta')
    for p in ['/opt/homebrew/bin/xdelta3', '/usr/local/bin/xdelta3']:
        if not xdelta and os.path.exists(p):
            xdelta = p
    return xdelta


def do_xdelta(args):
    """Apply an xdelta patch to a USA ISO."""
    usa_path = args[0]
    xdelta_path = args[1]
    out_path = args[2] if len(args) > 2 else 'FMA_Undub.iso'

    xdelta_bin = find_xdelta()
    if not xdelta_bin:
        print("ERROR: xdelta3 not found. Install it:")
        print("  macOS: brew install xdelta")
        print("  Linux: apt install xdelta3")
        sys.exit(1)

    print("Applying xdelta patch...")
    r = subprocess.run([xdelta_bin, '-d', '-s', usa_path, xdelta_path, out_path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"ERROR: {r.stderr}")
        sys.exit(1)

    print(f"Done! {out_path} ({os.path.getsize(out_path):,} bytes)")


def generate_xdelta(usa_iso_path, out_iso_path):
    """Generate an xdelta patch file from the patched ISO."""
    xdelta_bin = find_xdelta()
    if not xdelta_bin:
        print("WARNING: xdelta3 not found — can't generate patch")
        return

    xdelta_path = os.path.splitext(out_iso_path)[0] + '.xdelta'
    print("\nGenerating xdelta patch...")
    subprocess.run([xdelta_bin, '-9', '-S', 'djw', '-f', '-e', '-s',
        usa_iso_path, out_iso_path, xdelta_path], capture_output=True)

    if os.path.exists(xdelta_path):
        print(f"  {xdelta_path} ({os.path.getsize(xdelta_path) / (1024 * 1024):.0f}MB)")


# =============================================================================
# Audio-only mode
# =============================================================================

def do_audio(usa_iso_path, jp_iso_path, out_iso_path):
    """Audio-only undub: full JP DSIs (no size constraint) + CDDATA patching.

    Writes JP cutscenes sequentially into the ISO, relocating files and
    updating ISO9660 directory entries. No bitrate-constrained encoding.
    """
    print("Reading ISOs...")
    with open(usa_iso_path, 'rb') as f:
        usa_iso = f.read()
    with open(jp_iso_path, 'rb') as f:
        jp_iso = f.read()

    shutil.copy2(usa_iso_path, out_iso_path)

    # --- Step 1: Patch CDDATA.DIG (in-place, same size) ---
    mapping = build_mapping(usa_iso, jp_iso)
    print(f"  Mapping: {len(mapping)} entries")

    print("Patching CDDATA.DIG...")
    usa_cddata_info = find_file_in_iso(usa_iso, b'CDDATA.DIG;1')
    jp_cddata_info = find_file_in_iso(jp_iso, b'CDDATA.DIG;1')
    usa_dig = usa_iso[usa_cddata_info[0] * SECTOR:usa_cddata_info[0] * SECTOR + usa_cddata_info[1]]
    jp_dig = jp_iso[jp_cddata_info[0] * SECTOR:jp_cddata_info[0] * SECTOR + jp_cddata_info[1]]

    patched_dig, replaced, skipped_same, skipped_nofit = patch_cddata(usa_dig, jp_dig, mapping)
    print(f"  Replaced: {replaced}, Skipped (identical): {skipped_same}, Skipped (too large): {skipped_nofit}")

    with open(out_iso_path, 'r+b') as f:
        f.seek(usa_cddata_info[0] * SECTOR)
        f.write(patched_dig[:usa_cddata_info[1]])

    # --- Step 2: Write JP DSIs sequentially ---
    print("Writing JP cutscenes...")

    # DSIs start right after CDDATA.DIG
    cddata_end = usa_cddata_info[0] + (usa_cddata_info[1] + SECTOR - 1) // SECTOR
    write_sector = cddata_end

    with open(out_iso_path, 'r+b') as f:
        for name in DSI_NAMES:
            usa_info = find_file_in_iso(usa_iso, f'{name}.DSI;1'.encode())
            jp_info = find_file_in_iso(jp_iso, f'{name}.DSI;1'.encode())
            if not usa_info or not jp_info:
                continue

            jp_sec, jp_sz, _ = jp_info
            jp_dsi = jp_iso[jp_sec * SECTOR:jp_sec * SECTOR + jp_sz]

            f.seek(write_sector * SECTOR)
            f.write(jp_dsi)
            pad = (SECTOR - (jp_sz % SECTOR)) % SECTOR
            if pad:
                f.write(b'\x00' * pad)

            update_dir_entry(f, usa_info[2], write_sector, jp_sz)

            file_sectors = (jp_sz + SECTOR - 1) // SECTOR
            print(f"  {name}: {jp_sz / 1024 / 1024:.1f} MB")
            write_sector += file_sectors

        # DATA0 (runtime scratchpad) — relocate after last DSI
        data0_info = find_file_in_iso(usa_iso, b'DATA0')
        if data0_info:
            data0_sec, data0_sz, data0_dir = data0_info
            data0_content = usa_iso[data0_sec * SECTOR:data0_sec * SECTOR + data0_sz]
            f.seek(write_sector * SECTOR)
            f.write(data0_content)
            update_dir_entry(f, data0_dir, write_sector, data0_sz)
            write_sector += (data0_sz + SECTOR - 1) // SECTOR

        # Truncate ISO to actual size
        f.seek(write_sector * SECTOR)
        f.truncate()

    return usa_iso, jp_iso


# =============================================================================
# Full mode (audio + subtitles)
# =============================================================================

def do_full(usa_iso_path, jp_iso_path, out_iso_path, dump_mkv_dir=None):
    """Full pipeline: JP audio + burned English subtitles on all cutscenes.

    For each cutscene:
    1. Take JP DSI (video + audio)
    2. Burn English subtitles onto JP video
    3. Remux with dsi-muxer (auto block count, no size constraint)
    4. Write sequentially into ISO, relocating files as needed
    """
    print("Reading ISOs...")
    with open(usa_iso_path, 'rb') as f:
        usa_iso = f.read()
    with open(jp_iso_path, 'rb') as f:
        jp_iso = f.read()

    shutil.copy2(usa_iso_path, out_iso_path)

    # --- Step 1: Patch CDDATA.DIG ---
    mapping = build_mapping(usa_iso, jp_iso)
    print(f"  Mapping: {len(mapping)} entries")

    print("Patching CDDATA.DIG...")
    usa_cddata_info = find_file_in_iso(usa_iso, b'CDDATA.DIG;1')
    jp_cddata_info = find_file_in_iso(jp_iso, b'CDDATA.DIG;1')
    usa_dig = usa_iso[usa_cddata_info[0] * SECTOR:usa_cddata_info[0] * SECTOR + usa_cddata_info[1]]
    jp_dig = jp_iso[jp_cddata_info[0] * SECTOR:jp_cddata_info[0] * SECTOR + jp_cddata_info[1]]

    patched_dig, replaced, skipped_same, skipped_nofit = patch_cddata(usa_dig, jp_dig, mapping)
    print(f"  Replaced: {replaced}, Skipped (identical): {skipped_same}, Skipped (too large): {skipped_nofit}")

    with open(out_iso_path, 'r+b') as f:
        f.seek(usa_cddata_info[0] * SECTOR)
        f.write(patched_dig[:usa_cddata_info[1]])

    # --- Step 2: Build subtitled DSIs and write sequentially ---
    ffmpeg_bin = find_or_build_ffmpeg()
    if not ffmpeg_bin:
        print("WARNING: Could not get ffmpeg with libass — falling back to audio-only")

    if dump_mkv_dir:
        os.makedirs(dump_mkv_dir, exist_ok=True)

    print("Writing cutscenes...")
    cddata_end = usa_cddata_info[0] + (usa_cddata_info[1] + SECTOR - 1) // SECTOR
    write_sector = cddata_end

    with open(out_iso_path, 'r+b') as f:
        for name in DSI_NAMES:
            usa_info = find_file_in_iso(usa_iso, f'{name}.DSI;1'.encode())
            jp_info = find_file_in_iso(jp_iso, f'{name}.DSI;1'.encode())
            if not usa_info or not jp_info:
                continue

            jp_sec, jp_sz, _ = jp_info
            jp_dsi_bytes = jp_iso[jp_sec * SECTOR:jp_sec * SECTOR + jp_sz]

            # Try to build subtitled DSI
            ass_path = os.path.join(SUBS_DIR, f'{name}.ass')
            has_subs = (ffmpeg_bin and os.path.exists(ass_path) and
                        'Dialogue:' in open(ass_path).read())

            if has_subs:
                sub_dsi = build_subtitled_dsi(ffmpeg_bin, jp_dsi_bytes, ass_path)

                if dump_mkv_dir and sub_dsi is not None:
                    from dsi_muxer import DSI
                    src = DSI.from_bytes(jp_dsi_bytes)
                    mkv_path = os.path.join(dump_mkv_dir, f'{name}.mkv')
                    dump_mkv(ffmpeg_bin, sub_dsi, src.extract_audio(), mkv_path)
                    if os.path.exists(mkv_path):
                        print(f"    -> {mkv_path}")
            else:
                sub_dsi = None

            dsi_data = sub_dsi if sub_dsi is not None else jp_dsi_bytes
            label = "subtitled" if sub_dsi is not None else "JP audio"

            f.seek(write_sector * SECTOR)
            f.write(dsi_data)
            pad = (SECTOR - (len(dsi_data) % SECTOR)) % SECTOR
            if pad:
                f.write(b'\x00' * pad)

            update_dir_entry(f, usa_info[2], write_sector, len(dsi_data))

            file_sectors = (len(dsi_data) + SECTOR - 1) // SECTOR
            print(f"  {name}: {len(dsi_data) / 1024 / 1024:.1f} MB ({label})")
            write_sector += file_sectors

        # DATA0
        data0_info = find_file_in_iso(usa_iso, b'DATA0')
        if data0_info:
            data0_sec, data0_sz, data0_dir = data0_info
            data0_content = usa_iso[data0_sec * SECTOR:data0_sec * SECTOR + data0_sz]
            f.seek(write_sector * SECTOR)
            f.write(data0_content)
            update_dir_entry(f, data0_dir, write_sector, data0_sz)
            write_sector += (data0_sz + SECTOR - 1) // SECTOR

        f.seek(write_sector * SECTOR)
        f.truncate()


# =============================================================================
# CLI
# =============================================================================

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    mode = sys.argv[1]
    args = [a for a in sys.argv[2:] if not a.startswith('--')]
    skip_verify = '--skip-verify' in sys.argv
    want_xdelta = '--generate-xdelta' in sys.argv
    dump_mkv_dir = None
    for i, a in enumerate(sys.argv):
        if a == '--dump-mkv' and i + 1 < len(sys.argv):
            dump_mkv_dir = sys.argv[i + 1]

    print("Fullmetal Alchemist — Undub Patcher")
    print("=" * 40)

    if mode == 'xdelta':
        if len(args) < 2:
            print("Usage: patch.py xdelta <usa_iso> <xdelta_file> [output_iso]")
            sys.exit(1)
        if not skip_verify:
            verify_iso(args[0], 'USA', EXPECTED_HASHES['usa'], skip_verify)
        do_xdelta(args)

    elif mode in ('audio', 'full'):
        if len(args) < 2:
            print(f"Usage: patch.py {mode} <usa_iso> <jp_iso> [output_iso]")
            sys.exit(1)

        usa_path = args[0]
        jp_path = args[1]
        out_path = args[2] if len(args) > 2 else 'FMA_Undub.iso'

        if not skip_verify:
            verify_iso(usa_path, 'USA', EXPECTED_HASHES['usa'])
            verify_iso(jp_path, 'JP', EXPECTED_HASHES['jp'])

        print()
        if mode == 'full':
            do_full(usa_path, jp_path, out_path, dump_mkv_dir=dump_mkv_dir)
        else:
            do_audio(usa_path, jp_path, out_path)

        print(f"\nDone! {out_path} ({os.path.getsize(out_path):,} bytes)")

        if want_xdelta:
            generate_xdelta(usa_path, out_path)

    else:
        print(f"Unknown mode: {mode}")
        print("Use: full, audio, or xdelta")
        sys.exit(1)

    print("\nLoad in PCSX2 — use memory card saves, not save states.")


if __name__ == '__main__':
    main()
