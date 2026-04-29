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
    SECTOR, EXPECTED_HASHES, DSI_NAMES, SUBS_DIR,
)
from lib.iso import (
    find_file_in_iso, read_file_from_iso, write_file_to_iso, verify_iso,
)
from lib.cddata import build_mapping, patch_cddata
from lib.video import build_subtitled_dsi, dump_mkv
from lib.ffmpeg import find_or_build_ffmpeg
from dsi_muxer import DSI


# =============================================================================
# xdelta
# =============================================================================

def find_xdelta():
    """Find xdelta3 binary on PATH or in standard Homebrew/system locations."""
    if found := shutil.which('xdelta3') or shutil.which('xdelta'):
        return found
    for p in ['/opt/homebrew/bin/xdelta3', '/usr/local/bin/xdelta3']:
        if os.path.exists(p):
            return p
    return None


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
    """Audio-only undub: JP CDDATA + JP DSIs, all relocated at end of ISO."""
    print("Reading ISOs...")
    with open(usa_iso_path, 'rb') as f:
        usa_iso = f.read()
    with open(jp_iso_path, 'rb') as f:
        jp_iso = f.read()

    shutil.copy2(usa_iso_path, out_iso_path)

    mapping = build_mapping(usa_iso, jp_iso)
    print(f"  Mapping: {len(mapping)} entries")

    print("Patching CDDATA.DIG...")
    usa_dig, cddata_dir = read_file_from_iso(usa_iso, b'CDDATA.DIG;1')
    jp_dig, _ = read_file_from_iso(jp_iso, b'CDDATA.DIG;1')
    patched_dig, replaced, skipped_same, grown = patch_cddata(usa_dig, jp_dig, mapping)
    print(f"  Replaced: {replaced}, Skipped (identical): {skipped_same}, Grown: {grown}")

    # Relocate CDDATA + DSIs + DATA0 to end of ISO. Reusing the original
    # CDDATA region as the staging area for the new layout.
    usa_cddata_info = find_file_in_iso(usa_iso, b'CDDATA.DIG;1')
    write_sector = usa_cddata_info[0]

    with open(out_iso_path, 'r+b') as f:
        write_sector = write_file_to_iso(f, cddata_dir, write_sector, patched_dig)

        print("Writing JP cutscenes...")
        for name in DSI_NAMES:
            jp = read_file_from_iso(jp_iso, f'{name}.DSI;1'.encode())
            usa_info = find_file_in_iso(usa_iso, f'{name}.DSI;1'.encode())
            if jp is None or usa_info is None:
                continue
            jp_dsi, _ = jp
            print(f"  {name}: {len(jp_dsi) / 1024 / 1024:.1f} MB")
            write_sector = write_file_to_iso(f, usa_info[2], write_sector, jp_dsi)

        data0 = read_file_from_iso(usa_iso, b'DATA0')
        if data0 is not None:
            data0_content, data0_dir = data0
            write_sector = write_file_to_iso(f, data0_dir, write_sector, data0_content)

        f.seek(write_sector * SECTOR)
        f.truncate()


# =============================================================================
# Full mode (audio + subtitles)
# =============================================================================

def do_full(usa_iso_path, jp_iso_path, out_iso_path, dump_mkv_dir=None):
    """Full pipeline: JP audio + burned English subtitles on all cutscenes."""
    print("Reading ISOs...")
    with open(usa_iso_path, 'rb') as f:
        usa_iso = f.read()
    with open(jp_iso_path, 'rb') as f:
        jp_iso = f.read()

    shutil.copy2(usa_iso_path, out_iso_path)

    mapping = build_mapping(usa_iso, jp_iso)
    print(f"  Mapping: {len(mapping)} entries")

    print("Patching CDDATA.DIG...")
    usa_dig, cddata_dir = read_file_from_iso(usa_iso, b'CDDATA.DIG;1')
    jp_dig, _ = read_file_from_iso(jp_iso, b'CDDATA.DIG;1')
    patched_dig, replaced, skipped_same, grown = patch_cddata(usa_dig, jp_dig, mapping)
    print(f"  Replaced: {replaced}, Skipped (identical): {skipped_same}, Grown: {grown}")

    ffmpeg_bin = find_or_build_ffmpeg()
    if not ffmpeg_bin:
        print("WARNING: Could not get ffmpeg with libass — falling back to audio-only")

    if dump_mkv_dir:
        os.makedirs(dump_mkv_dir, exist_ok=True)

    usa_cddata_info = find_file_in_iso(usa_iso, b'CDDATA.DIG;1')
    write_sector = usa_cddata_info[0]

    with open(out_iso_path, 'r+b') as f:
        write_sector = write_file_to_iso(f, cddata_dir, write_sector, patched_dig)

        print("Writing cutscenes...")
        for name in DSI_NAMES:
            jp = read_file_from_iso(jp_iso, f'{name}.DSI;1'.encode())
            usa_info = find_file_in_iso(usa_iso, f'{name}.DSI;1'.encode())
            if jp is None or usa_info is None:
                continue
            jp_dsi_bytes, _ = jp

            ass_path = os.path.join(SUBS_DIR, f'{name}.ass')
            has_subs = False
            if ffmpeg_bin and os.path.exists(ass_path):
                with open(ass_path) as af:
                    has_subs = 'Dialogue:' in af.read()

            sub_dsi = None
            if has_subs:
                sub_dsi = build_subtitled_dsi(ffmpeg_bin, jp_dsi_bytes, ass_path)

                if dump_mkv_dir and sub_dsi is not None:
                    src = DSI.from_bytes(jp_dsi_bytes)
                    sub = DSI.from_bytes(sub_dsi)
                    with tempfile.TemporaryDirectory() as mkv_tmp:
                        m2v_path = os.path.join(mkv_tmp, f'{name}.m2v')
                        with open(m2v_path, 'wb') as mf:
                            mf.write(sub.extract_video())
                        mkv_path = os.path.join(dump_mkv_dir, f'{name}.mkv')
                        dump_mkv(ffmpeg_bin, m2v_path, src.extract_audio(), mkv_path)
                        if os.path.exists(mkv_path):
                            print(f"    -> {mkv_path}")

            dsi_data = sub_dsi if sub_dsi is not None else jp_dsi_bytes
            label = "subtitled" if sub_dsi is not None else "JP audio"
            print(f"  {name}: {len(dsi_data) / 1024 / 1024:.1f} MB ({label})")
            write_sector = write_file_to_iso(f, usa_info[2], write_sector, dsi_data)

        data0 = read_file_from_iso(usa_iso, b'DATA0')
        if data0 is not None:
            data0_content, data0_dir = data0
            write_sector = write_file_to_iso(f, data0_dir, write_sector, data0_content)

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
    skip_verify = '--skip-verify' in sys.argv
    want_xdelta = '--generate-xdelta' in sys.argv
    dump_mkv_dir = None
    skip_next = False
    args = []
    for i, a in enumerate(sys.argv[2:], start=2):
        if skip_next:
            skip_next = False
            continue
        if a == '--dump-mkv' and i + 1 < len(sys.argv):
            dump_mkv_dir = sys.argv[i + 1]
            skip_next = True
        elif not a.startswith('--'):
            args.append(a)

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

        # Update the Primary Volume Descriptor's volume-space-size field.
        # The PVD lives at sector 16; the field is at offset 80, stored as
        # an LE u32 followed by a BE u32. PCSX2 ignores it but real PS2
        # hardware refuses to load discs whose PVD size disagrees with the
        # actual image length.
        final = os.path.getsize(out_path)
        final_sectors = (final + SECTOR - 1) // SECTOR
        with open(out_path, 'r+b') as f:
            f.seek(16 * SECTOR + 80)
            f.write(struct.pack('<I', final_sectors))
            f.write(struct.pack('>I', final_sectors))

        print(f"\nDone! {out_path} ({final:,} bytes)")

        if want_xdelta:
            generate_xdelta(usa_path, out_path)

    else:
        print(f"Unknown mode: {mode}")
        print("Use: full, audio, or xdelta")
        sys.exit(1)

    print("\nLoad in PCSX2 — use memory card saves, not save states.")


if __name__ == '__main__':
    main()
