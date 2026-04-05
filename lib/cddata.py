"""
CDDATA.DIG patching — replaces audio entries with Japanese versions.

The CDDATA.DIG file is Racjin's game archive containing all non-cutscene
audio: dialogue, combat voices, SFX, music, and menu sounds.

Patching strategy:
1. Skip identical entries (shared SFX/music between regions)
2. Direct replacement when JP data fits in the USA slot
3. Racjin recompression when JP data is too large but compressible
4. SCEI per-sample replacement for sound banks (voice only, SFX preserved)
5. Keep USA version if nothing else works (never truncate)
"""

import struct
import os
import shutil
import subprocess
import tempfile

from .constants import SECTOR, SCEI_BANK_MAP, USA_TABLE_OFFSET, JP_TABLE_OFFSET, TABLE_ENTRY_COUNT
from .iso import find_file_in_iso

from racjin import compress as racjin_compress, decompress as racjin_decompress


# =============================================================================
# ADPCM Resampling (psxavenc pipeline)
# =============================================================================

def _find_tool(names):
    """Find a binary from a list of candidate paths."""
    for p in names:
        if p and os.path.exists(p):
            return p
    w = shutil.which(names[0]) if names else None
    return w


def _fit_sample_psxavenc(jp_adpcm, jp_rate, target_bytes):
    """Re-encode a JP ADPCM sample to fit in a target byte budget.

    Uses vgmstream to decode, ffmpeg to resample, and psxavenc to re-encode.
    Returns resampled ADPCM bytes, or None on failure.
    """
    psxavenc = _find_tool(['/tmp/psxavenc/build/psxavenc', 'psxavenc'])
    vgmstream = _find_tool(['/opt/homebrew/bin/vgmstream-cli', '/usr/local/bin/vgmstream-cli', 'vgmstream-cli'])
    ffmpeg = _find_tool(['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', 'ffmpeg'])

    if not psxavenc or not vgmstream or not ffmpeg:
        return None

    target_blocks = target_bytes // 16
    target_samples = target_blocks * 28
    duration = (len(jp_adpcm) / 16 * 28) / jp_rate if jp_rate > 0 else 0
    if duration <= 0:
        return None
    target_rate = max(4000, min(int(target_samples / duration), jp_rate))

    try:
        with tempfile.TemporaryDirectory() as tmp:
            adpcm_path = os.path.join(tmp, 'in.adpcm')
            with open(adpcm_path, 'wb') as f:
                f.write(jp_adpcm)
            with open(adpcm_path + '.txth', 'w') as f:
                f.write(f'codec = PSX\nchannels = 1\nsample_rate = {jp_rate}\nnum_samples = data_size\n')

            wav_path = os.path.join(tmp, 'decoded.wav')
            subprocess.run([vgmstream, '-o', wav_path, adpcm_path], capture_output=True, timeout=30)
            if not os.path.exists(wav_path):
                return None

            resampled_path = os.path.join(tmp, 'resampled.wav')
            subprocess.run([ffmpeg, '-y', '-i', wav_path, '-ar', str(target_rate), '-ac', '1',
                            resampled_path], capture_output=True, timeout=30)
            if not os.path.exists(resampled_path):
                return None

            vag_path = os.path.join(tmp, 'out.vag')
            subprocess.run([psxavenc, '-t', 'vag', '-f', str(target_rate),
                            resampled_path, vag_path], capture_output=True, timeout=30)
            if not os.path.exists(vag_path):
                return None

            with open(vag_path, 'rb') as f:
                vag = f.read()
            result = bytearray(vag[48:])  # strip VAG header
            if len(result) > target_bytes:
                result = result[:target_bytes]

            # Fix ADPCM flags: psxavenc omits END/LOOP markers that
            # the PS2 SPU2 needs. Without END, the voice reads past
            # the sample boundary, corrupting audio over time.
            if len(result) >= 16:
                result[1] = 0x06  # first block: LOOP_START + LOOP
                last_block = len(result) - 16
                result[last_block + 1] = 0x01  # last block: END
            result = bytes(result)
            return result
    except Exception:
        return None


# =============================================================================
# SCEI Sound Bank Parsing
# =============================================================================

def _parse_scei_samples(bank):
    """Parse an SCEI sound bank and return per-sample info.

    SCEI banks contain: SCEIVers (version), SCEIVagi (sample table),
    SCEISets (instrument sets), and audio data. The Vagi chunk holds
    per-sample metadata: cumulative BD offsets and sample rates.

    Args:
        bank: Raw bytes of the SCEI sound bank.

    Returns:
        List of (abs_offset, size, sample_rate) tuples, or None if not SCEI.
    """
    # SCEI tags are stored as LE uint32 pairs
    scei_vagi = struct.pack('<II', 0x53434549, 0x56616769)
    pos = bank.find(scei_vagi)
    if pos < 0:
        return None

    # Read Vagi chunk: [8-byte tag] [4-byte size] [data...]
    vagi_sz = struct.unpack('<I', bank[pos + 8:pos + 12])[0]
    vagi = bank[pos + 12:pos + 12 + vagi_sz]

    # Audio data base offset from container header
    audio_base = struct.unpack('<I', bank[28:32])[0]

    # Parse: [sample_count:4] [BD offsets: (count+1)*4] [padding] [params: count*8]
    sc = struct.unpack('<I', vagi[0:4])[0]

    # Find where per-sample parameters start (after BD offset table + padding)
    param_off = 4 + (sc + 1) * 4
    if param_off % 4 != 0:
        param_off += 4 - (param_off % 4)
    while param_off < len(vagi) and struct.unpack('<I', vagi[param_off:param_off + 4])[0] == 0:
        param_off += 4

    # Read per-sample params: [rate:u16] [flags:u16] [cumulative_offset:u32]
    samples = []
    prev_cum = 0
    for i in range(sc):
        p = param_off + i * 8
        if p + 8 > len(vagi):
            break
        rate = struct.unpack('<H', vagi[p:p + 2])[0]
        cum = struct.unpack('<I', vagi[p + 4:p + 8])[0]
        sz = cum - prev_cum
        samples.append((audio_base + prev_cum, sz, rate if rate > 0 else 44100))
        prev_cum = cum

    return samples


def _patch_scei_bank(usa_bank, jp_bank):
    """Replace voice samples in an SCEI bank while preserving SFX.

    Compares each sample by MD5 hash: identical = shared SFX (skip),
    different = voice content (replace if JP fits in USA slot).
    The bank structure and total size remain unchanged.

    Args:
        usa_bank: Raw bytes of the USA SCEI sound bank.
        jp_bank: Raw bytes of the JP SCEI sound bank.

    Returns:
        Patched bank bytes, or None if no samples were replaced.
    """
    usa_s = _parse_scei_samples(usa_bank)
    jp_s = _parse_scei_samples(jp_bank)
    if not usa_s or not jp_s:
        return None

    # Detect index offset when JP has more samples than USA.
    # JP may have leading SFX samples that USA's bank omits.
    jp_offset = 0
    if len(jp_s) > len(usa_s):
        best_shared = sum(1 for i in range(min(len(usa_s), len(jp_s)))
                          if usa_bank[usa_s[i][0]:usa_s[i][0] + usa_s[i][1]] ==
                          jp_bank[jp_s[i][0]:jp_s[i][0] + jp_s[i][1]])
        for k in range(1, len(jp_s) - len(usa_s) + 1):
            shared = sum(1 for i in range(len(usa_s))
                         if i + k < len(jp_s) and
                         usa_bank[usa_s[i][0]:usa_s[i][0] + usa_s[i][1]] ==
                         jp_bank[jp_s[i + k][0]:jp_s[i + k][0] + jp_s[i + k][1]])
            if shared > best_shared:
                best_shared = shared
                jp_offset = k
        # When no shared samples at any offset, default to aligning voice tails
        if best_shared == 0:
            jp_offset = len(jp_s) - len(usa_s)

    out = bytearray(usa_bank)
    replaced = 0

    for i, (u_off, u_sz, u_rate) in enumerate(usa_s):
        j = i + jp_offset
        if j >= len(jp_s):
            break
        j_off, j_sz, j_rate = jp_s[j]

        # Skip identical samples (shared SFX — same hash)
        if usa_bank[u_off:u_off + u_sz] == jp_bank[j_off:j_off + j_sz]:
            continue

        # Replace voice sample if JP fits in the USA slot
        if j_sz <= u_sz:
            out[u_off:u_off + j_sz] = jp_bank[j_off:j_off + j_sz]
            if j_sz < u_sz:
                out[u_off + j_sz:u_off + u_sz] = b'\x00' * (u_sz - j_sz)
            replaced += 1
            continue

        # JP sample too large — resample to fit using psxavenc
        fitted = _fit_sample_psxavenc(jp_bank[j_off:j_off + j_sz], j_rate, u_sz)
        if fitted:
            out[u_off:u_off + len(fitted)] = fitted
            if len(fitted) < u_sz:
                out[u_off + len(fitted):u_off + u_sz] = b'\x00' * (u_sz - len(fitted))
            replaced += 1

    return bytes(out) if replaced > 0 else None


# =============================================================================
# CDDATA TOC Helpers
# =============================================================================

def _write_cddata_entry(out, data_offset, data, slot_size, toc_offset, comp_size, decomp_size):
    """Write data into a CDDATA slot and update its TOC entry.

    Args:
        out: Mutable bytearray of the full CDDATA.DIG.
        data_offset: Byte offset where data should be written.
        data: The data bytes to write.
        slot_size: Total available slot size (zero-pads remainder).
        toc_offset: Byte offset of this entry's TOC record.
        comp_size: New compressed size for the TOC.
        decomp_size: New decompressed size for the TOC.
    """
    out[data_offset:data_offset + len(data)] = data
    out[data_offset + len(data):data_offset + slot_size] = b'\x00' * (slot_size - len(data))
    struct.pack_into('<I', out, toc_offset + 4, comp_size)
    struct.pack_into('<I', out, toc_offset + 12, decomp_size)


# =============================================================================
# Entry Mapping
# =============================================================================

def build_mapping(usa_iso, jp_iso):
    """Build the USA→JP CDDATA entry index mapping.

    Combines two sources:
    1. Executable lookup tables (101 dialogue/cutscene entries)
    2. SCEI bank map (97 combat voice/SFX entries)

    Args:
        usa_iso: Full bytes of the USA ISO.
        jp_iso: Full bytes of the JP ISO.

    Returns:
        Dict mapping USA entry indices to JP entry indices.
    """
    # Read game executables
    usa_exe = jp_exe = None
    for search, target in [(b'SLUS_209.94;1', 'usa'), (b'SLPM_654.73;1', 'jp')]:
        iso = usa_iso if target == 'usa' else jp_iso
        info = find_file_in_iso(iso, search)
        if info:
            sec, sz, _ = info
            exe = iso[sec * SECTOR:sec * SECTOR + sz]
            if target == 'usa':
                usa_exe = exe
            else:
                jp_exe = exe

    if not usa_exe or not jp_exe:
        raise RuntimeError("Could not find game executables in ISOs")

    # Read lookup tables from both executables
    mapping = {}
    usa_map = [struct.unpack('<I', usa_exe[USA_TABLE_OFFSET + i * 4:USA_TABLE_OFFSET + i * 4 + 4])[0]
               for i in range(TABLE_ENTRY_COUNT)]
    jp_map = [struct.unpack('<I', jp_exe[JP_TABLE_OFFSET + i * 4:JP_TABLE_OFFSET + i * 4 + 4])[0]
              for i in range(TABLE_ENTRY_COUNT)]
    for i in range(TABLE_ENTRY_COUNT):
        mapping[usa_map[i]] = jp_map[i]

    # Add SCEI bank mappings
    for u, j in SCEI_BANK_MAP.items():
        if u not in mapping:
            mapping[u] = j

    return mapping


# =============================================================================
# Main Patching Function
# =============================================================================

def patch_cddata(usa_dig, jp_dig, mapping):
    """Patch CDDATA.DIG by replacing USA entries with JP equivalents.

    Processing order per entry:
    1. Skip if USA and JP data are byte-identical (shared content)
    2. Direct copy if JP compressed data fits in USA slot
    3. Racjin recompress if JP data is larger but compressible
    4. SCEI per-sample replacement for sound banks
    5. Keep USA version if nothing works (never truncate/corrupt)

    Args:
        usa_dig: Full bytes of USA CDDATA.DIG.
        jp_dig: Full bytes of JP CDDATA.DIG.
        mapping: Dict mapping USA entry indices to JP entry indices.

    Returns:
        Tuple of (patched_bytes, replaced_count, skipped_identical, skipped_nofit).
    """
    out = bytearray(usa_dig)
    replaced = skipped_identical = skipped_nofit = 0
    scei_vagi_marker = struct.pack('<II', 0x53434549, 0x56616769)

    for usa_entry, jp_entry in sorted(mapping.items()):
        # Read USA TOC: [sector, comp_size, flags, decomp_size]
        usa_toc = usa_entry * 16
        if usa_toc + 16 > len(out):
            continue
        usa_sector, usa_comp_size = struct.unpack('<II', out[usa_toc:usa_toc + 8])
        if usa_sector == 0 or usa_comp_size == 0:
            continue

        # Read JP TOC
        jp_toc = jp_entry * 16
        if jp_toc + 16 > len(jp_dig):
            continue
        jp_sector, jp_comp_size, _, jp_decomp_size = struct.unpack('<IIII', jp_dig[jp_toc:jp_toc + 16])
        if jp_sector == 0 or jp_comp_size == 0:
            continue

        jp_raw = jp_dig[jp_sector * SECTOR:jp_sector * SECTOR + jp_comp_size]
        usa_raw = out[usa_sector * SECTOR:usa_sector * SECTOR + usa_comp_size]
        slot_size = usa_comp_size
        data_offset = usa_sector * SECTOR

        # 1. Skip identical entries (shared SFX/music)
        if jp_raw == usa_raw:
            skipped_identical += 1
            continue

        # 2. Direct replacement if JP fits
        if len(jp_raw) <= slot_size:
            _write_cddata_entry(out, data_offset, jp_raw, slot_size, usa_toc, len(jp_raw), jp_decomp_size)
            replaced += 1
            continue

        # 3. Try Racjin recompression
        if jp_comp_size != jp_decomp_size:
            try:
                jp_decompressed = racjin_decompress(jp_raw, jp_decomp_size)
                recompressed = racjin_compress(jp_decompressed)
                best = recompressed if len(recompressed) < len(jp_decompressed) else bytes(jp_decompressed)
                if len(best) <= slot_size:
                    _write_cddata_entry(out, data_offset, best, slot_size, usa_toc,
                                        len(best), len(jp_decompressed))
                    replaced += 1
                    continue
            except Exception:
                pass

        # 4. SCEI per-sample replacement (voice only, SFX preserved)
        if scei_vagi_marker in bytes(usa_raw):
            patched_bank = _patch_scei_bank(bytes(usa_raw), jp_raw)
            if patched_bank:
                out[data_offset:data_offset + len(patched_bank)] = patched_bank
                replaced += 1
                continue

        # 5. Can't fit — keep USA version intact
        skipped_nofit += 1

    return bytes(out), replaced, skipped_identical, skipped_nofit
