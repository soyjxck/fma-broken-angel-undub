"""
Video encoding and DSI muxing for subtitled cutscenes.

This module handles:
1. MPEG-2 encoding with burned ASS subtitles
2. Proportional audio DSI muxing (the key algorithm for A/V sync)
3. MKV export with squeezed JP audio

The proportional audio algorithm distributes audio per block based on
the number of video frames in that block. This ensures each block's
audio duration matches its video duration, producing perfect A/V sync
on PS2 hardware regardless of the video encoder used.
"""

import struct
import os
import shutil
import subprocess

from .constants import DSI_BLOCK_SIZE, AUDIO_TYPE_TAG, VIDEO_TYPE_TAG

from dsi_muxer.container import _count_markers

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_fontsdir():
    """Find a directory containing custom fonts for subtitle rendering."""
    candidates = [
        os.path.join(_REPO_ROOT, 'fonts'),
        os.path.expanduser('~/Library/Fonts'),
        '/Library/Fonts',
        '/usr/share/fonts',
    ]
    for d in candidates:
        if os.path.isdir(d):
            return d
    return None


def _count_pics(data):
    """Count MPEG-2 picture start codes (00 00 01 00) in video data."""
    return _count_markers(data, b'\x00\x00\x01\x00')


# =============================================================================
# MPEG-2 Encoding
# =============================================================================

def encode_subtitled_video(ffmpeg_bin, m2v_path, ass_path, output_path, nblocks, total_audio):
    """Encode video with burned ASS subtitles as PS2-compatible MPEG-2.

    Calculates the optimal bitrate to maximize DSI block utilization:
    higher bitrate = more blocks filled with video = better quality.

    Encoding parameters match the original TMPGEnc output:
    - IBBP GOP structure, closed GOPs, 9-bit DC precision
    - Non-linear quantizer, alternate intra VLC table
    - NTSC color metadata, SAR 7:6 for 4:3 display

    Args:
        ffmpeg_bin: Path to ffmpeg binary.
        m2v_path: Input MPEG-2 video (USA original).
        ass_path: ASS subtitle file to burn.
        output_path: Where to write the encoded .m2v.
        nblocks: Number of DSI blocks (determines bitrate target).
        total_audio: Total audio bytes (determines per-block audio budget).

    Returns:
        True on success, False on failure.
    """
    # Get frame count and duration from source
    ffprobe = os.path.join(os.path.dirname(ffmpeg_bin), 'ffprobe')
    if not os.path.exists(ffprobe):
        ffprobe = shutil.which('ffprobe') or ffmpeg_bin

    r = subprocess.run([ffprobe, '-v', 'error', '-count_frames', '-select_streams', 'v:0',
        '-show_entries', 'stream=nb_read_frames,r_frame_rate',
        '-of', 'csv=p=0', m2v_path], capture_output=True, text=True, timeout=120)
    parts = r.stdout.strip().split(',')
    if len(parts) < 2:
        return False

    num, den = parts[0].split('/')
    fps = int(num) / int(den)
    frames = int(parts[1])
    duration = frames / fps

    # Calculate optimal bitrate to fill blocks
    avg_audio_per_block = total_audio // nblocks
    avg_vid_capacity = (DSI_BLOCK_SIZE - 64) - avg_audio_per_block
    target_bytes = nblocks * avg_vid_capacity
    bitrate = int(target_bytes * 8 / duration / 1000)

    # Encode with PS2-compatible MPEG-2 parameters
    subprocess.run([ffmpeg_bin, '-y', '-i', m2v_path,
        '-vf', f'ass={ass_path}' + (f':fontsdir={_find_fontsdir()}' if _find_fontsdir() else '') + ',format=yuv420p',
        '-c:v', 'mpeg2video',
        '-b:v', f'{bitrate}k', '-minrate', f'{bitrate}k', '-maxrate', f'{bitrate}k',
        '-bufsize', '1835008', '-qmin', '1', '-qmax', '12',
        '-s', '512x448', '-sar', '7:6', '-r', '30000/1001',
        '-g', '16', '-bf', '2', '-b_strategy', '0',
        '-mpv_flags', '+strict_gop', '-dc', '9',
        '-intra_vlc', '1', '-non_linear_quant', '1',
        '-i_qfactor', '0.4', '-b_qfactor', '4.0',
        '-color_primaries', '5', '-color_trc', '5', '-colorspace', '4',
        '-video_format', 'ntsc',
        '-an', output_path], capture_output=True, timeout=600)

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


# =============================================================================
# DSI Muxer — Proportional Audio Algorithm
# =============================================================================

def mux_dsi_proportional(video_data, audio_data, nblocks):
    """Mux video + audio into DSI blocks with proportional audio.

    THE KEY ALGORITHM: Each block gets audio proportional to its video
    frame count. This ensures audio duration ≈ video duration per block,
    producing perfect A/V sync on PS2 hardware.

    The video is byte-sliced as a continuous stream — GOPs flow freely
    across block boundaries, exactly like the original game files.

    Last block uses the original's V→A structure with end-of-sequence.

    Args:
        video_data: MPEG-2 elementary stream (with end-of-sequence).
        audio_data: PS2 SPU ADPCM audio stream.
        nblocks: Number of DSI blocks to create.

    Returns:
        Complete DSI file as bytes.
    """
    usable = DSI_BLOCK_SIZE - 64  # bytes available per block (after header)
    total_frames = _count_pics(video_data)
    audio_per_frame = len(audio_data) / total_frames if total_frames > 0 else 512

    out = bytearray(nblocks * DSI_BLOCK_SIZE)
    vid_pos = 0
    aud_pos = 0

    for blk in range(nblocks):
        base = blk * DSI_BLOCK_SIZE
        is_last = (blk == nblocks - 1)

        if is_last:
            # Last block matches original structure: V→A, small sizes, slack
            aud_sz = 5120
            vid_cap = 65472
        else:
            # Estimate frames in this block's byte range
            est_aud = max(512, (round(8 * audio_per_frame) // 512) * 512)
            est_vid_cap = usable - est_aud
            chunk = video_data[vid_pos:vid_pos + est_vid_cap] if vid_pos < len(video_data) else b''
            actual_frames = _count_pics(chunk)

            # Audio proportional to frame count
            aud_sz = max(512, (round(actual_frames * audio_per_frame) // 512) * 512)
            vid_cap = usable - aud_sz

        # Byte-slice video from continuous stream
        vc = video_data[vid_pos:vid_pos + vid_cap] if vid_pos < len(video_data) else b''
        if len(vc) < vid_cap:
            vc += b'\x00' * (vid_cap - len(vc))

        # Audio chunk
        ac = audio_data[aud_pos:aud_pos + aud_sz]
        if len(ac) < aud_sz:
            ac += b'\x00' * (aud_sz - len(ac))

        # Write block header + data
        if is_last:
            # V→A order for last block (matches original)
            struct.pack_into('<IIiIIiII', out, base,
                2, 64, VIDEO_TYPE_TAG, vid_cap,
                64 + vid_cap, AUDIO_TYPE_TAG, aud_sz, 0)
            out[base + 32:base + 64] = b'\x00' * 32
            out[base + 64:base + 64 + vid_cap] = bytes(vc)[:vid_cap]
            out[base + 64 + vid_cap:base + 64 + vid_cap + aud_sz] = ac[:aud_sz]
        else:
            # A→V order for normal blocks
            struct.pack_into('<IIiIIiII', out, base,
                2, 64, AUDIO_TYPE_TAG, aud_sz,
                64 + aud_sz, VIDEO_TYPE_TAG, vid_cap, 0)
            out[base + 32:base + 64] = b'\x00' * 32
            out[base + 64:base + 64 + aud_sz] = ac
            out[base + 64 + aud_sz:base + 64 + aud_sz + vid_cap] = bytes(vc)[:vid_cap]

        vid_pos += vid_cap
        aud_pos += aud_sz

    # Post-process: ensure end-of-sequence marker exists in the last block
    # with video data. Without this, the game won't transition after the cutscene.
    end_marker = b'\x00\x00\x01\xb7'
    for blk in range(nblocks - 1, -1, -1):
        base = blk * DSI_BLOCK_SIZE
        hdr = struct.unpack('<IIiIIiII', out[base:base + 32])
        if hdr[2] == VIDEO_TYPE_TAG:
            v_off, v_sz = base + hdr[1], hdr[3]
        else:
            v_off, v_sz = base + hdr[4], hdr[6]
        region = out[v_off:v_off + v_sz]
        if end_marker in region:
            break  # already has one
        # Find last nonzero byte and inject marker
        last_nz = v_sz - 1
        while last_nz > 0 and region[last_nz] == 0:
            last_nz -= 1
        if last_nz > 0 and last_nz + 5 < v_sz:
            out[v_off + last_nz + 1:v_off + last_nz + 5] = end_marker
            break

    return bytes(out)


# =============================================================================
# DSI Stream Extraction (for audio-only mode)
# =============================================================================

def extract_dsi_audio(dsi_data):
    """Extract the continuous audio stream from a DSI file."""
    chunks = []
    for blk in range(len(dsi_data) // DSI_BLOCK_SIZE):
        base = blk * DSI_BLOCK_SIZE
        hdr = struct.unpack('<IIiIIiII', dsi_data[base:base + 32])
        if hdr[2] == AUDIO_TYPE_TAG:
            chunks.append(dsi_data[base + hdr[1]:base + hdr[1] + hdr[3]])
        else:
            chunks.append(dsi_data[base + hdr[4]:base + hdr[4] + hdr[6]])
    return b''.join(chunks)


def extract_dsi_video(dsi_data):
    """Extract the continuous video stream from a DSI file."""
    chunks = []
    for blk in range(len(dsi_data) // DSI_BLOCK_SIZE):
        base = blk * DSI_BLOCK_SIZE
        hdr = struct.unpack('<IIiIIiII', dsi_data[base:base + 32])
        if hdr[2] == VIDEO_TYPE_TAG:
            chunks.append(dsi_data[base + hdr[1]:base + hdr[1] + hdr[3]])
        else:
            chunks.append(dsi_data[base + hdr[4]:base + hdr[4] + hdr[6]])
    return b''.join(chunks)


def patch_dsi_audio(usa_dsi, jp_audio):
    """Replace audio in a USA DSI with JP audio (preserves block structure)."""
    out = bytearray(usa_dsi)
    pos = 0
    for blk in range(len(out) // DSI_BLOCK_SIZE):
        base = blk * DSI_BLOCK_SIZE
        hdr = struct.unpack('<IIiIIiII', out[base:base + 32])
        if hdr[2] == AUDIO_TYPE_TAG:
            a_off, a_sz = base + hdr[1], hdr[3]
        else:
            a_off, a_sz = base + hdr[4], hdr[6]
        chunk = jp_audio[pos:pos + a_sz]
        if len(chunk) < a_sz:
            chunk += b'\x00' * (a_sz - len(chunk))
        out[a_off:a_off + a_sz] = chunk
        pos += a_sz
    return bytes(out)


# =============================================================================
# MKV Export
# =============================================================================

def dump_mkv(ffmpeg_bin, m2v_path, jp_audio, tmp_dir, mkv_path):
    """Export a subtitled cutscene as MKV with squeezed JP audio.

    The DSI audio is ~8.9% longer than the video due to block padding
    accumulation. We squeeze with atempo=1.0886 to match video duration.

    Args:
        ffmpeg_bin: Path to ffmpeg binary.
        m2v_path: Encoded .m2v video with burned subtitles.
        jp_audio: Raw JP ADPCM audio bytes.
        tmp_dir: Temp directory for intermediate files.
        mkv_path: Output MKV path.
    """
    adpcm_path = os.path.join(tmp_dir, 'audio.adpcm')
    txth_path = adpcm_path + '.txth'
    wav_path = os.path.join(tmp_dir, 'audio.wav')
    squeezed_path = os.path.join(tmp_dir, 'audio_sq.wav')

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
