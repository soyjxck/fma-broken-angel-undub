"""
Video encoding and DSI muxing for subtitled cutscenes.

This module handles:
1. MPEG-2 encoding with burned ASS subtitles
2. DSI muxing via dsi-muxer
3. MKV export with JP audio
"""

import os
import re
import shutil
import subprocess
import tempfile

from dsi_muxer import DSI

_FONT_DIRS = [
    os.path.expanduser('~/Library/Fonts'),
    '/Library/Fonts',
    '/System/Library/Fonts',
    '/System/Library/Fonts/Supplemental',
    '/usr/share/fonts',
    '/usr/local/share/fonts',
]


def _find_fontsdir():
    """Find a directory containing fonts for subtitle rendering."""
    for d in _FONT_DIRS:
        if os.path.isdir(d):
            return d
    return None


# =============================================================================
# MPEG-2 Encoding
# =============================================================================

def encode_subtitled_video(ffmpeg_bin, m2v_path, ass_path, output_path):
    """Encode video with burned ASS subtitles as PS2-compatible MPEG-2.

    Uses high-quality CBR encoding at 7000k — no size constraint since
    DSI block count is auto-calculated from content size.

    Args:
        ffmpeg_bin: Path to ffmpeg binary.
        m2v_path: Input MPEG-2 video.
        ass_path: ASS subtitle file to burn.
        output_path: Where to write the encoded .m2v.

    Returns:
        True on success, False on failure.

    Raises:
        RuntimeError: If libass reports missing fonts.
    """
    ass_filter = f'ass={ass_path}'
    fontsdir = _find_fontsdir()
    if fontsdir:
        ass_filter += f':fontsdir={fontsdir}'

    r = subprocess.run([ffmpeg_bin, '-y', '-i', m2v_path,
        '-vf', f'{ass_filter},format=yuv420p',
        '-c:v', 'mpeg2video',
        '-b:v', '7000k', '-minrate', '7000k', '-maxrate', '7000k',
        '-bufsize', '1835008', '-qmin', '1', '-qmax', '12',
        '-s', '512x448', '-sar', '7:6', '-r', '30000/1001',
        '-g', '16', '-bf', '2', '-b_strategy', '0',
        '-mpv_flags', '+strict_gop', '-dc', '9',
        '-intra_vlc', '1', '-non_linear_quant', '1',
        '-i_qfactor', '0.4', '-b_qfactor', '4.0',
        '-color_primaries', '5', '-color_trc', '5', '-colorspace', '4',
        '-video_format', 'ntsc',
        '-an', output_path], capture_output=True, text=True, timeout=600)

    # Check for missing font warnings from libass
    if r.stderr and 'fontselect' in r.stderr.lower() and 'failed' in r.stderr.lower():
        fonts = re.findall(r"Glyph.*?font '([^']+)'", r.stderr)
        if not fonts:
            fonts = re.findall(r"(?:fontselect|SelectFont).*?'([^']+)'", r.stderr)
        raise RuntimeError(
            f"Missing fonts for subtitle rendering: {', '.join(set(fonts)) or 'unknown'}\n"
            f"  Install them to ~/Library/Fonts (macOS) or /usr/share/fonts (Linux)")

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        return False

    # Ensure end-of-sequence marker exists
    with open(output_path, 'rb') as f:
        vid = bytearray(f.read())
    if vid.rfind(b'\x00\x00\x01\xb7') < 0:
        last = len(vid)
        while last > 0 and vid[last - 1] == 0:
            last -= 1
        vid = vid[:last]
        vid.extend(b'\x00\x00\x01\xb7')
        with open(output_path, 'wb') as f:
            f.write(vid)

    return True


def build_subtitled_dsi(ffmpeg_bin, jp_dsi_bytes, ass_path):
    """Build a subtitled DSI from JP DSI bytes and an ASS subtitle file.

    Pipeline:
        1. Demux JP DSI -> video + audio
        2. Burn subtitles onto video (MPEG-2 re-encode)
        3. Remux with dsi-muxer (auto block count)

    Returns DSI bytes, or None on failure.
    """
    dsi = DSI.from_bytes(jp_dsi_bytes)
    video = dsi.extract_video()
    audio = dsi.extract_audio()

    with tempfile.TemporaryDirectory() as tmp:
        m2v_in = os.path.join(tmp, 'input.m2v')
        m2v_out = os.path.join(tmp, 'output.m2v')

        with open(m2v_in, 'wb') as f:
            f.write(video)

        if not encode_subtitled_video(ffmpeg_bin, m2v_in, ass_path, m2v_out):
            return None

        with open(m2v_out, 'rb') as f:
            new_video = f.read()

    new_dsi = DSI.mux(new_video, audio)
    return new_dsi.to_bytes()


# =============================================================================
# MKV Export
# =============================================================================

def dump_mkv(ffmpeg_bin, m2v_path, jp_audio, mkv_path):
    """Export a subtitled cutscene as MKV with squeezed JP audio.

    The DSI audio is ~8.9% longer than the video due to block padding
    accumulation. We squeeze with atempo=1.0886 to match video duration.

    Args:
        ffmpeg_bin: Path to ffmpeg binary.
        m2v_path: Encoded .m2v video with burned subtitles.
        jp_audio: Raw JP ADPCM audio bytes.
        mkv_path: Output MKV path.
    """
    with tempfile.TemporaryDirectory() as tmp:
        adpcm_path = os.path.join(tmp, 'audio.adpcm')
        txth_path = adpcm_path + '.txth'
        wav_path = os.path.join(tmp, 'audio.wav')
        squeezed_path = os.path.join(tmp, 'audio_sq.wav')

        # Write raw ADPCM with vgmstream descriptor
        with open(adpcm_path, 'wb') as f:
            f.write(jp_audio)
        with open(txth_path, 'w') as f:
            f.write('codec = PSX\nchannels = 2\nsample_rate = 44100\n'
                    'interleave = 0x100\nnum_samples = data_size\n')

        # Decode ADPCM to WAV with vgmstream
        vgmstream = shutil.which('vgmstream-cli')
        for p in ['/opt/homebrew/bin/vgmstream-cli', '/usr/local/bin/vgmstream-cli']:
            if not vgmstream and os.path.exists(p):
                vgmstream = p
        if vgmstream:
            subprocess.run([vgmstream, '-o', wav_path, adpcm_path],
                           capture_output=True, timeout=120)

        # Squeeze audio to match video duration (DSI audio is ~8.9% longer)
        if os.path.exists(wav_path):
            subprocess.run([ffmpeg_bin, '-y', '-i', wav_path,
                '-af', 'atempo=1.0886', '-ar', '44100', '-ac', '2',
                squeezed_path], capture_output=True, timeout=120)

        # Mux video + squeezed audio into MKV
        mux_args = [ffmpeg_bin, '-y', '-i', m2v_path]
        if os.path.exists(squeezed_path):
            mux_args += ['-i', squeezed_path,
                         '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
                         '-c:a', 'aac', '-b:a', '192k',
                         '-r', '30000/1001', '-shortest', mkv_path]
        else:
            mux_args += ['-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
                         '-r', '30000/1001', '-an', mkv_path]
        subprocess.run(mux_args, capture_output=True, timeout=300)
