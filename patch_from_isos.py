#!/usr/bin/env python3
"""
FMA Undub — Patch from ISOs
=============================

Generates the undubbed ISO directly from the USA and JP ISOs.
No xdelta or DeltaPatcher required.

Usage:
    python3 patch_from_isos.py <usa_iso> <jp_iso> [output_iso]

Example:
    python3 patch_from_isos.py \
        "Fullmetal Alchemist and the Broken Angel (USA).iso" \
        "Hagane no Renkinjutsushi - Tobenai Tenshi (Japan).iso" \
        "FMA_Undub.iso"
"""

import struct
import os
import sys
import shutil

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

# SCEI sound bank mapping (hash-matched + voice-only)
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

def find_files_in_iso(iso_data):
    """Find file positions by searching for known filenames in ISO directory."""
    files = {}
    for search, name in [(b'CDDATA.DIG;1', 'CDDATA.DIG'),
                         (b'M000.DSI;1', 'M000.DSI'), (b'M001.DSI;1', 'M001.DSI'),
                         (b'M002.DSI;1', 'M002.DSI'), (b'M003.DSI;1', 'M003.DSI'),
                         (b'M004.DSI;1', 'M004.DSI'), (b'M005.DSI;1', 'M005.DSI'),
                         (b'M006.DSI;1', 'M006.DSI'), (b'M008.DSI;1', 'M008.DSI'),
                         (b'M010.DSI;1', 'M010.DSI'), (b'M014.DSI;1', 'M014.DSI'),
                         (b'M015.DSI;1', 'M015.DSI'), (b'M016.DSI;1', 'M016.DSI'),
                         (b'M018.DSI;1', 'M018.DSI'), (b'M021.DSI;1', 'M021.DSI'),
                         (b'M022.DSI;1', 'M022.DSI'), (b'M023.DSI;1', 'M023.DSI'),
                         (b'M024.DSI;1', 'M024.DSI'), (b'M025.DSI;1', 'M025.DSI')]:
        pos = iso_data.find(search)
        if pos >= 0:
            entry_start = pos - 33
            sector = struct.unpack('<I', iso_data[entry_start+2:entry_start+6])[0]
            size = struct.unpack('<I', iso_data[entry_start+10:entry_start+14])[0]
            files[name] = (sector, size, entry_start)
    return files


def extract_file_from_iso(iso_data, sector, size):
    """Read a file from the ISO at the given sector."""
    return iso_data[sector * SECTOR_SIZE : sector * SECTOR_SIZE + size]


# =============================================================================
# DSI Patching
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


def patch_dsi_audio(usa_dsi, jp_audio):
    """Replace audio in USA DSI with JP audio, return patched DSI."""
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
            chunk = chunk + b'\x00' * (a_sz - len(chunk))
        out[a_off:a_off+a_sz] = chunk
        pos += a_sz
    return bytes(out)


# =============================================================================
# CDDATA.DIG Patching
# =============================================================================

def read_cddata_entries(dig_data):
    min_sector = len(dig_data) // SECTOR_SIZE
    for i in range(min(1024, len(dig_data) // 16)):
        s = struct.unpack('<I', dig_data[i*16:i*16+4])[0]
        if 0 < s < min_sector: min_sector = s
    return min_sector * SECTOR_SIZE // 16


def patch_cddata(usa_dig, jp_dig, mapping):
    """Patch CDDATA.DIG entries in-place."""
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
            out[bo:bo+len(jr)] = jr
            out[bo+len(jr):bo+sl] = b'\x00' * (sl - len(jr))
            struct.pack_into('<I', out, o+4, len(jr))
            struct.pack_into('<I', out, o+12, jd)
            replaced += 1
        else:
            if jc != jd:
                try: jpd = racjin_decompress(jr, jd)
                except: continue
            else: jpd = jr
            jpr = racjin_compress(jpd)
            best = jpr if len(jpr) < len(jpd) else bytes(jpd)
            if len(best) <= sl:
                out[bo:bo+len(best)] = best
                out[bo+len(best):bo+sl] = b'\x00' * (sl - len(best))
                struct.pack_into('<I', out, o+4, len(best))
                struct.pack_into('<I', out, o+12, len(jpd))
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
                    out[bo:bo+len(bd)] = bd
                    out[bo+len(bd):bo+sl] = b'\x00' * (sl - len(bd))
                    struct.pack_into('<I', out, o+4, len(bd))
                    struct.pack_into('<I', out, o+12, bt)
                    truncated += 1

    return bytes(out), replaced, truncated


# =============================================================================
# Main
# =============================================================================

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    usa_iso_path = sys.argv[1]
    jp_iso_path = sys.argv[2]
    out_iso_path = sys.argv[3] if len(sys.argv) > 3 else "FMA_Undub.iso"

    for p, n in [(usa_iso_path, "USA ISO"), (jp_iso_path, "JP ISO")]:
        if not os.path.exists(p):
            print(f"ERROR: {n} not found: {p}")
            sys.exit(1)

    print("Fullmetal Alchemist — Undub Patcher")
    print("=" * 40)

    # Copy USA ISO as base
    print(f"\nCopying USA ISO...")
    shutil.copy2(usa_iso_path, out_iso_path)

    # Read both ISOs
    print("Reading ISOs...")
    with open(usa_iso_path, 'rb') as f: usa_iso = f.read()
    with open(jp_iso_path, 'rb') as f: jp_iso = f.read()

    # Find file positions
    usa_files = find_files_in_iso(usa_iso)
    jp_files = find_files_in_iso(jp_iso)

    # Find executables for mapping tables
    usa_exe = None; jp_exe = None
    for pos in range(len(usa_iso) - 8):
        if usa_iso[pos:pos+8] == b'SLUS_209':
            # Search backwards for the file entry
            break
    # Use known positions from the file table
    for name, (sec, sz, _) in usa_files.items():
        if name == 'CDDATA.DIG': continue
        data = extract_file_from_iso(usa_iso, sec, min(sz, 16))
        break

    # Read mapping tables from executables (embedded in ISOs)
    # Find SLUS/SLPM by scanning
    usa_exe_data = None; jp_exe_data = None
    for search, target in [(b'SLUS_209.94', 'usa'), (b'SLPM_654.73', 'jp')]:
        iso = usa_iso if target == 'usa' else jp_iso
        pos = iso.find(search)
        if pos >= 0:
            # Find the directory entry
            entry = pos - 33
            sec = struct.unpack('<I', iso[entry+2:entry+6])[0]
            sz = struct.unpack('<I', iso[entry+10:entry+14])[0]
            exe = extract_file_from_iso(iso, sec, sz)
            if target == 'usa': usa_exe_data = exe
            else: jp_exe_data = exe

    if not usa_exe_data or not jp_exe_data:
        print("ERROR: Could not find game executables in ISOs")
        sys.exit(1)

    # Build mapping
    mapping = {}
    usa_map = [struct.unpack('<I', usa_exe_data[USA_TABLE_OFFSET+i*4:USA_TABLE_OFFSET+i*4+4])[0] for i in range(TABLE_ENTRY_COUNT)]
    jp_map = [struct.unpack('<I', jp_exe_data[JP_TABLE_OFFSET+i*4:JP_TABLE_OFFSET+i*4+4])[0] for i in range(TABLE_ENTRY_COUNT)]
    for i in range(TABLE_ENTRY_COUNT):
        mapping[usa_map[i]] = jp_map[i]
    for u, j in SCEI_BANK_MAP.items():
        if u not in mapping: mapping[u] = j

    print(f"  Audio mapping: {len(mapping)} entries")

    # Patch CDDATA.DIG
    print("\nPatching CDDATA.DIG...")
    cddata_sec, cddata_sz, _ = usa_files['CDDATA.DIG']
    usa_dig = extract_file_from_iso(usa_iso, cddata_sec, cddata_sz)

    jp_cddata_files = find_files_in_iso(jp_iso)
    # Find JP CDDATA by scanning for its table
    jp_cddata_pos = None
    for search in [b'CDDATA.DIG;1']:
        p = jp_iso.find(search)
        if p >= 0:
            e = p - 33
            jp_cddata_sec = struct.unpack('<I', jp_iso[e+2:e+6])[0]
            jp_cddata_sz = struct.unpack('<I', jp_iso[e+10:e+14])[0]
            jp_dig = extract_file_from_iso(jp_iso, jp_cddata_sec, jp_cddata_sz)
            break

    patched_dig, replaced, truncated = patch_cddata(usa_dig, jp_dig, mapping)
    print(f"  Replaced: {replaced}, Truncated: {truncated}")

    # Write CDDATA to output ISO
    with open(out_iso_path, 'r+b') as f:
        f.seek(cddata_sec * SECTOR_SIZE)
        f.write(patched_dig[:cddata_sz])

    # Patch DSI cutscene files
    print("\nPatching cutscene audio...")
    dsi_names = ['M000','M001','M002','M003','M004','M005','M006','M008',
                 'M010','M014','M015','M016','M018','M021','M022','M023','M024','M025']

    for name in dsi_names:
        dsi_file = f'{name}.DSI'
        if dsi_file not in usa_files: continue

        usa_sec, usa_sz, usa_dir_entry = usa_files[dsi_file]

        # Find JP DSI
        jp_dsi_file = dsi_file.lower().replace('.dsi', '.dsi')
        jp_sec = jp_sz = None
        # Search JP ISO for this DSI file
        search = f'{name}.DSI;1'.encode()
        p = jp_iso.find(search)
        if p >= 0:
            e = p - 33
            jp_sec = struct.unpack('<I', jp_iso[e+2:e+6])[0]
            jp_sz = struct.unpack('<I', jp_iso[e+10:e+14])[0]

        if jp_sec is None: continue

        if name == 'M000':
            # Special case: M000 uses full JP DSI (different video)
            jp_dsi = extract_file_from_iso(jp_iso, jp_sec, jp_sz)

            if jp_sz > usa_sz:
                # Overflow into DATA0 — patch ISO directory for new size
                with open(out_iso_path, 'r+b') as f:
                    f.seek(usa_sec * SECTOR_SIZE)
                    f.write(jp_dsi)
                    # Patch ISO9660 directory size
                    f.seek(usa_dir_entry + 10)
                    f.write(struct.pack('<I', jp_sz))
                    f.write(struct.pack('>I', jp_sz))
                print(f"  {name}: full JP DSI ({jp_sz/(1024*1024):.0f}MB, overflow into DATA0)")
            else:
                with open(out_iso_path, 'r+b') as f:
                    f.seek(usa_sec * SECTOR_SIZE)
                    f.write(jp_dsi)
                print(f"  {name}: full JP DSI")
        else:
            # Normal case: replace audio stream in USA DSI
            usa_dsi = extract_file_from_iso(usa_iso, usa_sec, usa_sz)
            jp_dsi = extract_file_from_iso(jp_iso, jp_sec, jp_sz)
            jp_audio = extract_dsi_audio(jp_dsi)
            patched_dsi = patch_dsi_audio(usa_dsi, jp_audio)

            with open(out_iso_path, 'r+b') as f:
                f.seek(usa_sec * SECTOR_SIZE)
                f.write(patched_dsi)
            print(f"  {name}: JP audio patched")

    print(f"\n{'=' * 40}")
    print(f"Done! Output: {out_iso_path}")
    print(f"  Size: {os.path.getsize(out_iso_path):,} bytes")
    print(f"\nLoad in PCSX2 — use memory card saves, not save states.")


if __name__ == '__main__':
    main()
