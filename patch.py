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
"""

import struct
import os
import sys
import shutil
import hashlib
import subprocess
import tempfile

# =============================================================================
# Constants
# =============================================================================

DSI_BLOCK_SIZE = 0x40000
AUDIO_TYPE_TAG = -8192
VIDEO_TYPE_TAG = -16384
SECTOR_SIZE = 2048

USA_TABLE_OFFSET = 0x1B612E
JP_TABLE_OFFSET = 0x1B52EE
TABLE_ENTRY_COUNT = 101

EXPECTED_HASHES = {
    'usa': {'size': 1927217152, 'md5': 'e074fae418feff31ee9b4c6422527cab'},
    'jp':  {'size': 1732345856, 'md5': '39ee7c7c9773731b9aa6dae943faaec3'},
}

SCEI_BANK_MAP = {
    78:39, 79:15, 81:197, 82:198, 84:199, 85:200, 86:219, 87:220,
    88:221, 89:222, 90:223, 91:248, 92:249, 93:250, 94:250, 95:250,
    96:250, 97:250, 98:255, 99:250, 100:257, 101:258, 102:259, 103:260,
    104:261, 106:263, 109:264, 110:265, 111:262, 112:268, 113:341, 114:555,
    116:557, 117:558, 118:559, 120:569, 123:572, 124:573, 125:574, 126:575,
    127:576, 128:577, 129:578, 130:322, 131:323, 132:561, 133:324, 140:331,
    144:332, 145:333, 147:335, 148:459, 149:460, 150:461, 154:465, 155:466,
    158:483, 159:484, 160:485, 161:486, 162:487, 163:488, 164:580, 165:581,
    166:582, 167:583, 168:584, 169:585, 170:586, 171:587, 172:588, 173:589,
    174:605, 175:606, 176:203, 177:607, 178:616, 179:608, 181:610, 182:611,
    183:203, 185:614, 186:615, 188:477, 189:477,
    105:491, 107:491, 108:491, 141:245, 142:462, 143:247, 146:334,
    151:462, 152:463, 153:464, 156:467, 157:468,
}

# Subtitle files are embedded in the subs/ directory alongside this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SUBS_DIR = os.path.join(SCRIPT_DIR, 'subs')


# =============================================================================
# Racjin Compression
# =============================================================================

def racjin_decompress(buffer, decompressed_size):
    index = 0; dest_index = 0; last_dec_byte = 0; bit_shift = 0
    frequencies = bytearray(256); seq_indices = [0] * 8192
    output = bytearray(decompressed_size)
    while index < len(buffer) - 1 and dest_index < decompressed_size:
        next_code = (buffer[index + 1] << 8) | buffer[index]
        next_code >>= bit_shift; bit_shift += 1; index += 1
        if bit_shift == 8: bit_shift = 0; index += 1
        seq_index = dest_index
        if next_code & 0x100:
            output[dest_index] = next_code & 0xFF; dest_index += 1
        else:
            key = ((next_code >> 3) & 0x1F) + last_dec_byte * 32
            src_index = seq_indices[key]; length = (next_code & 0x07) + 1
            for _ in range(length):
                if dest_index >= decompressed_size: break
                output[dest_index] = output[src_index]; dest_index += 1; src_index += 1
        if dest_index >= decompressed_size: break
        key = frequencies[last_dec_byte] + last_dec_byte * 32
        seq_indices[key] = seq_index
        frequencies[last_dec_byte] = (frequencies[last_dec_byte] + 1) & 0x1F
        last_dec_byte = output[dest_index - 1]
    return bytes(output)


def racjin_compress(data):
    buf = bytes(data); buf_len = len(buf)
    index = 0; last_enc_byte = 0; bit_shift = 0
    frequencies = [0] * 256; seq_indices = [0] * 8192; codes = []
    while index < buf_len:
        best_freq = 0; best_match = 0
        positions_to_check = min(frequencies[last_enc_byte], 32) & 0x1F
        seq_index = index
        for freq in range(positions_to_check):
            key = freq + last_enc_byte * 32; src_index = seq_indices[key]
            matched = 0; max_length = min(8, buf_len - index)
            for offset in range(max_length):
                if src_index + offset >= buf_len: break
                if buf[src_index + offset] == buf[index + offset]: matched += 1
                else: break
            if matched > best_match: best_freq = freq; best_match = matched
        if best_match > 0:
            code = (best_freq << 3) | (best_match - 1); index += best_match
        else:
            code = 0x100 | buf[index]; index += 1
        code <<= bit_shift; codes.append(code); bit_shift += 1
        if bit_shift == 8: bit_shift = 0
        key = (frequencies[last_enc_byte] & 0x1F) + last_enc_byte * 32
        seq_indices[key] = seq_index; frequencies[last_enc_byte] += 1
        last_enc_byte = buf[index - 1]
    compressed = bytearray()
    for i in range(0, len(codes), 8):
        group_size = min(8, len(codes) - i)
        for s in range(0, group_size + 1, 2):
            first = codes[s + i - 1] if s > 0 else 0x00
            middle = codes[s + i] if s < group_size else 0x00
            last = codes[s + i + 1] if s < group_size - 1 else 0x00
            result = middle | (first >> 8) | (last << 8)
            compressed.append(result & 0xFF)
            if s < group_size: compressed.append((result >> 8) & 0xFF)
    return bytes(compressed)


# =============================================================================
# ISO Helpers
# =============================================================================

def find_file_in_iso(iso_data, filename):
    """Find a file's sector, size, and directory entry offset in an ISO."""
    search = filename.encode() if isinstance(filename, str) else filename
    pos = iso_data.find(search)
    if pos < 0:
        return None
    entry = pos - 33
    sector = struct.unpack('<I', iso_data[entry+2:entry+6])[0]
    size = struct.unpack('<I', iso_data[entry+10:entry+14])[0]
    return sector, size, entry


def verify_iso(path, label, expected, skip=False):
    """Verify ISO size and MD5."""
    size = os.path.getsize(path)
    if size != expected['size']:
        print(f"  WARNING: {label} size mismatch ({size:,} vs {expected['size']:,})")

    if skip:
        return True

    print(f"  Verifying {label}...", end=' ', flush=True)
    with open(path, 'rb') as f:
        md5 = hashlib.md5(f.read()).hexdigest()
    if md5 == expected['md5']:
        print("OK")
        return True
    else:
        print(f"MISMATCH (got {md5})")
        print(f"  Your ISO may be a different dump. Proceeding anyway...")
        return False


# =============================================================================
# DSI Audio Patching
# =============================================================================

def extract_dsi_audio(dsi_data):
    audio = bytearray()
    for blk in range(len(dsi_data) // DSI_BLOCK_SIZE):
        off = blk * DSI_BLOCK_SIZE
        hdr = struct.unpack('<IIiIIiII', dsi_data[off:off+32])
        if hdr[2] == AUDIO_TYPE_TAG:
            audio.extend(dsi_data[off+hdr[1]:off+hdr[1]+hdr[3]])
        else:
            audio.extend(dsi_data[off+hdr[4]:off+hdr[4]+hdr[6]])
    return bytes(audio)


def extract_dsi_video(dsi_data):
    video = bytearray()
    for blk in range(len(dsi_data) // DSI_BLOCK_SIZE):
        off = blk * DSI_BLOCK_SIZE
        hdr = struct.unpack('<IIiIIiII', dsi_data[off:off+32])
        if hdr[2] == VIDEO_TYPE_TAG:
            video.extend(dsi_data[off+hdr[1]:off+hdr[1]+hdr[3]])
        else:
            video.extend(dsi_data[off+hdr[4]:off+hdr[4]+hdr[6]])
    return bytes(video)


def patch_dsi_audio(usa_dsi, jp_audio):
    out = bytearray(usa_dsi)
    pos = 0
    for blk in range(len(out) // DSI_BLOCK_SIZE):
        off = blk * DSI_BLOCK_SIZE
        hdr = struct.unpack('<IIiIIiII', out[off:off+32])
        if hdr[2] == AUDIO_TYPE_TAG:
            a_off = off + hdr[1]; a_sz = hdr[3]
        else:
            a_off = off + hdr[4]; a_sz = hdr[6]
        chunk = jp_audio[pos:pos+a_sz]
        if len(chunk) < a_sz:
            chunk += b'\x00' * (a_sz - len(chunk))
        out[a_off:a_off+a_sz] = chunk
        pos += a_sz
    return bytes(out)


def patch_dsi_video(dsi_data, new_video):
    out = bytearray(dsi_data)
    pos = 0
    for blk in range(len(out) // DSI_BLOCK_SIZE):
        off = blk * DSI_BLOCK_SIZE
        hdr = struct.unpack('<IIiIIiII', out[off:off+32])
        if hdr[2] == VIDEO_TYPE_TAG:
            v_off = off + hdr[1]; v_sz = hdr[3]
        else:
            v_off = off + hdr[4]; v_sz = hdr[6]
        chunk = new_video[pos:pos+v_sz]
        if len(chunk) < v_sz:
            chunk += b'\x00' * (v_sz - len(chunk))
        out[v_off:v_off+v_sz] = chunk
        pos += v_sz
    return bytes(out)


# =============================================================================
# CDDATA.DIG Patching
# =============================================================================

def patch_cddata(usa_dig, jp_dig, mapping):
    out = bytearray(usa_dig)
    replaced = 0; truncated = 0
    for usa_e, jp_e in sorted(mapping.items()):
        o = usa_e * 16
        if o + 16 > len(out): continue
        us, uc = struct.unpack('<II', out[o:o+8])
        if us == 0 or uc == 0: continue
        jo = jp_e * 16
        if jo + 16 > len(jp_dig): continue
        js, jc, _, jd = struct.unpack('<IIII', jp_dig[jo:jo+16])
        if js == 0 or jc == 0: continue
        jr = jp_dig[js*SECTOR_SIZE:js*SECTOR_SIZE+jc]
        sl = uc; bo = us * SECTOR_SIZE
        if len(jr) <= sl:
            out[bo:bo+len(jr)] = jr; out[bo+len(jr):bo+sl] = b'\x00'*(sl-len(jr))
            struct.pack_into('<I', out, o+4, len(jr)); struct.pack_into('<I', out, o+12, jd)
            replaced += 1
        else:
            if jc != jd:
                try: jpd = racjin_decompress(jr, jd)
                except: continue
            else: jpd = jr
            jpr = racjin_compress(jpd)
            best = jpr if len(jpr) < len(jpd) else bytes(jpd)
            if len(best) <= sl:
                out[bo:bo+len(best)] = best; out[bo+len(best):bo+sl] = b'\x00'*(sl-len(best))
                struct.pack_into('<I', out, o+4, len(best)); struct.pack_into('<I', out, o+12, len(jpd))
                replaced += 1
            else:
                lo, hi = 0, len(jpd); bd = None
                while lo < hi:
                    mid = (lo+hi+1)//2; tr = (mid//16)*16
                    if tr == 0: break
                    trial = racjin_compress(bytes(jpd[:tr]))
                    if len(trial) <= sl: bd = trial; bt = tr; lo = mid
                    else: hi = mid - 1
                if bd:
                    out[bo:bo+len(bd)] = bd; out[bo+len(bd):bo+sl] = b'\x00'*(sl-len(bd))
                    struct.pack_into('<I', out, o+4, len(bd)); struct.pack_into('<I', out, o+12, bt)
                    truncated += 1
    return bytes(out), replaced, truncated


# =============================================================================
# ffmpeg with libass (for subtitle burning)
# =============================================================================

def find_or_build_ffmpeg():
    """Find an ffmpeg with libass, or build one."""
    # Check common locations
    for path in ['/tmp/ffmpeg-custom/ffmpeg', '/tmp/ffmpeg-7.1.1/ffmpeg',
                 shutil.which('ffmpeg'), '/opt/homebrew/bin/ffmpeg',
                 '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg']:
        if path and os.path.exists(path):
            r = subprocess.run([path, '-filters'], capture_output=True, text=True)
            if 'subtitles' in r.stdout or 'ass' in r.stdout:
                return path

    # Need to build ffmpeg with libass
    print("\n  ffmpeg with libass not found. Building from source...")
    print("  This may take a few minutes on first run.\n")

    build_dir = '/tmp/ffmpeg-build'
    os.makedirs(build_dir, exist_ok=True)

    # Check dependencies based on platform
    import platform
    system = platform.system()

    if system == 'Darwin':
        for dep in ['libass', 'libx264', 'pkgconf']:
            r = subprocess.run(['brew', 'list', dep], capture_output=True)
            if r.returncode != 0:
                print(f"  Installing {dep}...")
                subprocess.run(['brew', 'install', dep], capture_output=True)
    elif system == 'Linux':
        # Check if libass is available via pkg-config
        r = subprocess.run(['pkg-config', '--exists', 'libass'], capture_output=True)
        if r.returncode != 0:
            print("  ERROR: libass not found. Install dependencies first:")
            print("    Debian/Ubuntu: sudo apt install libass-dev libx264-dev pkg-config build-essential")
            print("    Fedora: sudo dnf install libass-devel x264-devel pkgconf-pkg-config gcc make")
            return None

    # Download ffmpeg source
    ffmpeg_dir = os.path.join(build_dir, 'ffmpeg-7.1.1')
    if not os.path.exists(ffmpeg_dir):
        print("  Downloading ffmpeg source...")
        subprocess.run(['curl', '-sL', 'https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz',
                        '-o', os.path.join(build_dir, 'ffmpeg.tar.xz')], check=True)
        subprocess.run(['tar', 'xf', os.path.join(build_dir, 'ffmpeg.tar.xz'),
                        '-C', build_dir], check=True)

    # Get pkg-config flags
    pkg_config = shutil.which('pkg-config') or shutil.which('pkgconf') or 'pkg-config'
    r = subprocess.run([pkg_config, '--cflags', 'libass'], capture_output=True, text=True)
    ass_cflags = r.stdout.strip()
    r = subprocess.run([pkg_config, '--libs', 'libass'], capture_output=True, text=True)
    ass_libs = r.stdout.strip()

    # Configure and build
    print("  Configuring ffmpeg...")
    configure_args = [
        './configure', '--prefix=/tmp/ffmpeg-custom',
        '--enable-gpl', '--enable-libx264', '--enable-libass',
        f'--extra-cflags={ass_cflags}',
        f'--extra-ldflags={ass_libs}',
    ]

    if system == 'Darwin':
        configure_args[4] += ' -I/opt/homebrew/include'
        configure_args[5] += ' -L/opt/homebrew/lib'
        configure_args.extend(['--enable-videotoolbox', '--enable-audiotoolbox'])

    env = os.environ.copy()
    env['PKG_CONFIG'] = pkg_config
    subprocess.run(configure_args, cwd=ffmpeg_dir, capture_output=True, env=env)

    print("  Compiling ffmpeg (this takes a few minutes)...")
    cpus = os.cpu_count() or 4
    subprocess.run(['make', f'-j{cpus}'], cwd=ffmpeg_dir, capture_output=True)

    ffmpeg_bin = os.path.join(ffmpeg_dir, 'ffmpeg')
    if os.path.exists(ffmpeg_bin):
        print(f"  Built: {ffmpeg_bin}")
        return ffmpeg_bin

    print("  ERROR: ffmpeg build failed")
    return None


def burn_subtitles_on_video(ffmpeg_bin, m2v_path, ass_path, output_path, target_size):
    """Burn ASS subtitles onto MPEG-2 video with CBR matching target size."""
    # Find ffprobe next to ffmpeg
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
    bitrate = int(target_size * 8 / duration / 1000)

    # CBR encode with subtitles
    subprocess.run([ffmpeg_bin, '-y', '-i', m2v_path,
        '-vf', f'ass={ass_path}',
        '-c:v', 'mpeg2video',
        '-b:v', f'{bitrate}k', '-minrate', f'{bitrate}k', '-maxrate', f'{bitrate}k',
        '-bufsize', '2000k', '-qmin', '1', '-qmax', '3',
        '-s', '512x448', '-aspect', '4:3', '-r', '30000/1001',
        '-g', '15', '-bf', '2', '-an', output_path],
        capture_output=True, timeout=600)

    if not os.path.exists(output_path):
        return False

    # Add MPEG end code + pad/trim to target size
    with open(output_path, 'rb') as f:
        vid = bytearray(f.read())

    end_code = b'\x00\x00\x01\xb7'
    last = len(vid)
    while last > 0 and vid[last-1] == 0:
        last -= 1
    final = bytearray(vid[:last])
    final.extend(end_code)
    if len(final) < target_size:
        final.extend(b'\x00' * (target_size - len(final)))
    elif len(final) > target_size:
        final = bytearray(vid[:target_size-4])
        final.extend(end_code)

    with open(output_path, 'wb') as f:
        f.write(final)
    return True


# =============================================================================
# Build entry mapping from executables
# =============================================================================

def build_mapping(usa_iso, jp_iso):
    """Build the full USA->JP CDDATA entry mapping."""
    # Find executables
    usa_exe = jp_exe = None
    for search, target in [(b'SLUS_209.94;1', 'usa'), (b'SLPM_654.73;1', 'jp')]:
        iso = usa_iso if target == 'usa' else jp_iso
        info = find_file_in_iso(iso, search)
        if info:
            sec, sz, _ = info
            exe = iso[sec*SECTOR_SIZE:sec*SECTOR_SIZE+sz]
            if target == 'usa': usa_exe = exe
            else: jp_exe = exe

    if not usa_exe or not jp_exe:
        print("ERROR: Could not find game executables")
        sys.exit(1)

    mapping = {}
    usa_map = [struct.unpack('<I', usa_exe[USA_TABLE_OFFSET+i*4:USA_TABLE_OFFSET+i*4+4])[0]
               for i in range(TABLE_ENTRY_COUNT)]
    jp_map = [struct.unpack('<I', jp_exe[JP_TABLE_OFFSET+i*4:JP_TABLE_OFFSET+i*4+4])[0]
              for i in range(TABLE_ENTRY_COUNT)]
    for i in range(TABLE_ENTRY_COUNT):
        mapping[usa_map[i]] = jp_map[i]
    for u, j in SCEI_BANK_MAP.items():
        if u not in mapping:
            mapping[u] = j
    return mapping


# =============================================================================
# Patch Modes
# =============================================================================

DSI_NAMES = ['M000','M001','M002','M003','M004','M005','M006','M008',
             'M010','M014','M015','M016','M018','M021','M022','M023','M024','M025']


def do_xdelta(args):
    """Apply an xdelta patch to a USA ISO."""
    usa_path = args[0]
    xdelta_path = args[1]
    out_path = args[2] if len(args) > 2 else 'FMA_Undub.iso'

    xdelta_bin = shutil.which('xdelta3') or shutil.which('xdelta')
    for p in ['/opt/homebrew/bin/xdelta3', '/usr/local/bin/xdelta3']:
        if not xdelta_bin and os.path.exists(p): xdelta_bin = p

    if not xdelta_bin:
        print("ERROR: xdelta3 not found. Install it:")
        print("  macOS: brew install xdelta")
        print("  Linux: apt install xdelta3")
        sys.exit(1)

    print(f"Applying xdelta patch...")
    r = subprocess.run([xdelta_bin, '-d', '-s', usa_path, xdelta_path, out_path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"ERROR: {r.stderr}")
        sys.exit(1)

    print(f"Done! {out_path} ({os.path.getsize(out_path):,} bytes)")


def do_audio(usa_iso_path, jp_iso_path, out_iso_path):
    """Audio-only undub from both ISOs."""
    print("Reading ISOs...")
    with open(usa_iso_path, 'rb') as f: usa_iso = f.read()
    with open(jp_iso_path, 'rb') as f: jp_iso = f.read()

    shutil.copy2(usa_iso_path, out_iso_path)

    # CDDATA
    mapping = build_mapping(usa_iso, jp_iso)
    print(f"  Mapping: {len(mapping)} entries")

    print("Patching CDDATA.DIG...")
    info = find_file_in_iso(usa_iso, b'CDDATA.DIG;1')
    usa_dig = usa_iso[info[0]*SECTOR_SIZE:info[0]*SECTOR_SIZE+info[1]]
    jp_info = find_file_in_iso(jp_iso, b'CDDATA.DIG;1')
    jp_dig = jp_iso[jp_info[0]*SECTOR_SIZE:jp_info[0]*SECTOR_SIZE+jp_info[1]]

    patched_dig, replaced, truncated = patch_cddata(usa_dig, jp_dig, mapping)
    print(f"  Replaced: {replaced}, Truncated: {truncated}")

    with open(out_iso_path, 'r+b') as f:
        f.seek(info[0] * SECTOR_SIZE)
        f.write(patched_dig[:info[1]])

    # DSI files
    print("Patching cutscene audio...")
    for name in DSI_NAMES:
        usa_info = find_file_in_iso(usa_iso, f'{name}.DSI;1'.encode())
        jp_search = f'{name}.DSI;1'.encode()
        jp_dsi_info = find_file_in_iso(jp_iso, jp_search)
        if not usa_info or not jp_dsi_info: continue

        usa_sec, usa_sz, usa_dir = usa_info
        jp_sec, jp_sz, _ = jp_dsi_info

        if name == 'M000':
            jp_dsi = jp_iso[jp_sec*SECTOR_SIZE:jp_sec*SECTOR_SIZE+jp_sz]
            with open(out_iso_path, 'r+b') as f:
                f.seek(usa_sec * SECTOR_SIZE)
                f.write(jp_dsi)
                if jp_sz > usa_sz:
                    f.seek(usa_dir + 10)
                    f.write(struct.pack('<I', jp_sz))
                    f.write(struct.pack('>I', jp_sz))
            print(f"  {name}: full JP DSI")
        else:
            usa_dsi = usa_iso[usa_sec*SECTOR_SIZE:usa_sec*SECTOR_SIZE+usa_sz]
            jp_dsi = jp_iso[jp_sec*SECTOR_SIZE:jp_sec*SECTOR_SIZE+jp_sz]
            jp_audio = extract_dsi_audio(jp_dsi)
            patched = patch_dsi_audio(usa_dsi, jp_audio)
            with open(out_iso_path, 'r+b') as f:
                f.seek(usa_sec * SECTOR_SIZE)
                f.write(patched)
            print(f"  {name}: JP audio")

    return usa_iso, jp_iso


def do_full(usa_iso_path, jp_iso_path, out_iso_path):
    """Full pipeline: audio + subtitle-burned video."""
    # First do audio patching
    usa_iso, jp_iso = do_audio(usa_iso_path, jp_iso_path, out_iso_path)

    # Find or build ffmpeg with libass
    print("\nSetting up subtitle burning...")
    ffmpeg_bin = find_or_build_ffmpeg()
    if not ffmpeg_bin:
        print("WARNING: Could not get ffmpeg with libass — skipping subtitles")
        return

    # Burn subtitles into each cutscene's video
    print("Burning subtitles into cutscene video...")

    with open(out_iso_path, 'r+b') as iso_f:
        for name in DSI_NAMES:
            if name == 'M000':
                continue  # Opening uses full JP DSI, no subs

            ass_path = os.path.join(SUBS_DIR, f'{name}.ass')
            if not os.path.exists(ass_path):
                continue
            with open(ass_path) as f:
                if 'Dialogue:' not in f.read():
                    continue

            usa_info = find_file_in_iso(usa_iso, f'{name}.DSI;1'.encode())
            if not usa_info: continue
            usa_sec, usa_sz, _ = usa_info

            # Read current patched DSI from output ISO
            iso_f.seek(usa_sec * SECTOR_SIZE)
            dsi_data = iso_f.read(usa_sz)

            # Extract video
            video = extract_dsi_video(dsi_data)
            vid_size = len(video)

            with tempfile.TemporaryDirectory() as tmp:
                m2v_in = os.path.join(tmp, f'{name}.m2v')
                m2v_out = os.path.join(tmp, f'{name}_sub.m2v')

                with open(m2v_in, 'wb') as f:
                    f.write(video)

                if burn_subtitles_on_video(ffmpeg_bin, m2v_in, ass_path, m2v_out, vid_size):
                    with open(m2v_out, 'rb') as f:
                        new_video = f.read()
                    patched = patch_dsi_video(dsi_data, new_video)
                    iso_f.seek(usa_sec * SECTOR_SIZE)
                    iso_f.write(patched)
                    print(f"  {name}: subtitled")
                else:
                    print(f"  {name}: subtitle burn failed, keeping audio-only")


# =============================================================================
# xdelta generation
# =============================================================================

def generate_xdelta(usa_iso_path, out_iso_path):
    xdelta_bin = shutil.which('xdelta3') or shutil.which('xdelta')
    for p in ['/opt/homebrew/bin/xdelta3', '/usr/local/bin/xdelta3']:
        if not xdelta_bin and os.path.exists(p): xdelta_bin = p

    if not xdelta_bin:
        print("WARNING: xdelta3 not found — can't generate patch")
        return

    xdelta_path = os.path.splitext(out_iso_path)[0] + '.xdelta'
    print(f"\nGenerating xdelta patch...")
    subprocess.run([xdelta_bin, '-9', '-S', 'djw', '-f', '-e', '-s',
        usa_iso_path, out_iso_path, xdelta_path], capture_output=True)

    if os.path.exists(xdelta_path):
        print(f"  {xdelta_path} ({os.path.getsize(xdelta_path)/(1024*1024):.0f}MB)")


# =============================================================================
# Main
# =============================================================================

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    mode = sys.argv[1]
    args = [a for a in sys.argv[2:] if not a.startswith('--')]
    skip_verify = '--skip-verify' in sys.argv
    want_xdelta = '--generate-xdelta' in sys.argv

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
            do_full(usa_path, jp_path, out_path)
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
