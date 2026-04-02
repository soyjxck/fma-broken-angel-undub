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
    DSI_BLOCK_SIZE, SECTOR_SIZE, EXPECTED_HASHES,
    DSI_NAMES, SUBS_DIR,
)
from lib.iso import find_file_in_iso, verify_iso
from lib.cddata import build_mapping, patch_cddata
from lib.video import (
    extract_dsi_audio, extract_dsi_video, patch_dsi_audio,
    encode_subtitled_video, mux_dsi_proportional, dump_mkv,
)
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
    """Audio-only undub: JP audio in all cutscenes + CDDATA, no subtitles.

    This produces a perfectly playable ISO with Japanese voices and
    original English video. No ffmpeg required.
    """
    print("Reading ISOs...")
    with open(usa_iso_path, 'rb') as f:
        usa_iso = f.read()
    with open(jp_iso_path, 'rb') as f:
        jp_iso = f.read()

    shutil.copy2(usa_iso_path, out_iso_path)

    # Patch CDDATA.DIG
    mapping = build_mapping(usa_iso, jp_iso)
    print(f"  Mapping: {len(mapping)} entries")

    print("Patching CDDATA.DIG...")
    usa_cddata_info = find_file_in_iso(usa_iso, b'CDDATA.DIG;1')
    jp_cddata_info = find_file_in_iso(jp_iso, b'CDDATA.DIG;1')
    usa_dig = usa_iso[usa_cddata_info[0] * SECTOR_SIZE:usa_cddata_info[0] * SECTOR_SIZE + usa_cddata_info[1]]
    jp_dig = jp_iso[jp_cddata_info[0] * SECTOR_SIZE:jp_cddata_info[0] * SECTOR_SIZE + jp_cddata_info[1]]

    patched_dig, replaced, skipped_same, skipped_nofit = patch_cddata(usa_dig, jp_dig, mapping)
    print(f"  Replaced: {replaced}, Skipped (identical): {skipped_same}, Skipped (too large): {skipped_nofit}")

    with open(out_iso_path, 'r+b') as iso_f:
        iso_f.seek(usa_cddata_info[0] * SECTOR_SIZE)
        iso_f.write(patched_dig[:usa_cddata_info[1]])

        # Patch DSI cutscene audio
        print("Patching cutscene audio...")
        for name in DSI_NAMES:
            usa_info = find_file_in_iso(usa_iso, f'{name}.DSI;1'.encode())
            jp_info = find_file_in_iso(jp_iso, f'{name}.DSI;1'.encode())
            if not usa_info or not jp_info:
                continue

            usa_sec, usa_sz, usa_dir = usa_info
            jp_sec, jp_sz, _ = jp_info

            if name == 'M000':
                # Opening: replace entire DSI with JP version (different video+audio)
                jp_dsi = jp_iso[jp_sec * SECTOR_SIZE:jp_sec * SECTOR_SIZE + jp_sz]
                iso_f.seek(usa_sec * SECTOR_SIZE)
                iso_f.write(jp_dsi)
                if jp_sz > usa_sz:
                    # Patch ISO directory entry for larger file
                    iso_f.seek(usa_dir + 10)
                    iso_f.write(struct.pack('<I', jp_sz))
                    iso_f.write(struct.pack('>I', jp_sz))
                print(f"  {name}: full JP DSI")
            else:
                usa_dsi = usa_iso[usa_sec * SECTOR_SIZE:usa_sec * SECTOR_SIZE + usa_sz]
                jp_dsi = jp_iso[jp_sec * SECTOR_SIZE:jp_sec * SECTOR_SIZE + jp_sz]
                jp_audio = extract_dsi_audio(jp_dsi)
                patched = patch_dsi_audio(usa_dsi, jp_audio)
                iso_f.seek(usa_sec * SECTOR_SIZE)
                iso_f.write(patched)
                print(f"  {name}: JP audio")

    return usa_iso, jp_iso


# =============================================================================
# Full mode (audio + subtitles)
# =============================================================================

def do_full(usa_iso_path, jp_iso_path, out_iso_path, dump_mkv_dir=None):
    """Full pipeline: JP audio + burned English subtitles on all cutscenes.

    For each cutscene:
    1. Extract video (USA for most, JP for M000 opening)
    2. Encode with subtitles burned in (MPEG-2 CBR, PS2-compatible)
    3. Mux with proportional audio into DSI blocks (perfect A/V sync)
    4. Optionally export as MKV for preview
    """
    # First do audio-only patching (CDDATA + DSI audio)
    usa_iso, jp_iso = do_audio(usa_iso_path, jp_iso_path, out_iso_path)

    # Find or build ffmpeg with libass
    print("\nSetting up subtitle burning...")
    ffmpeg_bin = find_or_build_ffmpeg()
    if not ffmpeg_bin:
        print("WARNING: Could not get ffmpeg with libass — skipping subtitles")
        return

    if dump_mkv_dir:
        os.makedirs(dump_mkv_dir, exist_ok=True)

    # Burn subtitles + mux with proportional audio
    print("Burning subtitles into cutscene video...")

    with open(out_iso_path, 'r+b') as iso_f:
        for name in DSI_NAMES:
            ass_path = os.path.join(SUBS_DIR, f'{name}.ass')
            if not os.path.exists(ass_path):
                continue
            with open(ass_path) as f:
                if 'Dialogue:' not in f.read():
                    continue

            # M000 uses JP video (different opening), others use USA video
            if name == 'M000':
                jp_info = find_file_in_iso(jp_iso, f'{name}.DSI;1'.encode())
                usa_info = find_file_in_iso(usa_iso, f'{name}.DSI;1'.encode())
                if not jp_info or not usa_info:
                    continue
                jp_sec, jp_sz, _ = jp_info
                usa_sec, usa_sz, usa_dir = usa_info
                jp_dsi = jp_iso[jp_sec * SECTOR_SIZE:jp_sec * SECTOR_SIZE + jp_sz]
                src_video = extract_dsi_video(jp_dsi)
                jp_audio = extract_dsi_audio(jp_dsi)
                nblocks = jp_sz // DSI_BLOCK_SIZE
            else:
                usa_info = find_file_in_iso(usa_iso, f'{name}.DSI;1'.encode())
                if not usa_info:
                    continue
                usa_sec, usa_sz, _ = usa_info
                nblocks = usa_sz // DSI_BLOCK_SIZE
                iso_f.seek(usa_sec * SECTOR_SIZE)
                dsi_data = iso_f.read(usa_sz)
                src_video = extract_dsi_video(dsi_data)
                jp_audio = extract_dsi_audio(dsi_data)

            with tempfile.TemporaryDirectory() as tmp:
                m2v_in = os.path.join(tmp, f'{name}.m2v')
                m2v_out = os.path.join(tmp, f'{name}_sub.m2v')

                with open(m2v_in, 'wb') as f:
                    f.write(src_video)

                if encode_subtitled_video(ffmpeg_bin, m2v_in, ass_path, m2v_out,
                                          nblocks, len(jp_audio)):
                    with open(m2v_out, 'rb') as f:
                        new_video = f.read()
                    patched = mux_dsi_proportional(new_video, jp_audio, nblocks)

                    # Verify end-of-sequence
                    if b'\x00\x00\x01\xb7' not in patched:
                        print(f"  {name}: WARNING — missing end-of-sequence!")

                    # Write to ISO
                    if name == 'M000':
                        iso_f.seek(usa_sec * SECTOR_SIZE)
                        iso_f.write(patched)
                        if len(patched) > usa_sz:
                            iso_f.seek(usa_dir + 10)
                            iso_f.write(struct.pack('<I', len(patched)))
                            iso_f.write(struct.pack('>I', len(patched)))
                    else:
                        iso_f.seek(usa_sec * SECTOR_SIZE)
                        iso_f.write(patched)

                    print(f"  {name}: subtitled")

                    # Export MKV with squeezed JP audio
                    if dump_mkv_dir:
                        mkv_path = os.path.join(dump_mkv_dir, f'{name}.mkv')
                        dump_mkv(ffmpeg_bin, m2v_out, jp_audio, tmp, mkv_path)
                        if os.path.exists(mkv_path):
                            print(f"    -> {mkv_path}")
                else:
                    print(f"  {name}: subtitle burn failed, keeping audio-only")


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
