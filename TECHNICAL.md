# Fullmetal Alchemist and the Broken Angel (PS2) - Reverse Engineering Notes

**Game**: Fullmetal Alchemist and the Broken Angel (USA, SLUS_209.94)
**Platform**: PlayStation 2
**Goal**: Extract voice audio files for undub patch creation
**Date**: March 2026

---

## Table of Contents

1. [Quick Reference (TL;DR)](#quick-reference)
2. [Disc Layout](#disc-layout)
3. [DSI File Format (Cutscenes)](#dsi-file-format)
4. [CDDATA.DIG Format (Main Archive)](#cddatadig-format)
5. [Extraction Walkthrough](#extraction-walkthrough)
6. [Reverse Engineering Process](#reverse-engineering-process)
7. [Key Decisions & Breakthroughs](#key-decisions--breakthroughs)
8. [Pitfalls & Lessons Learned](#pitfalls--lessons-learned)
9. [Complete Changelog of Attempts](#complete-changelog-of-attempts)
10. [What Remains](#what-remains)
11. [Tools Used](#tools-used)
12. [Published Artifacts](#published-artifacts)

---

## Quick Reference

### DSI Audio Extraction (one-liner)

```bash
# 1. Extract raw ADPCM from DSI file
python3 extract_dsi_audio.py M000.DSI M000_audio.adpcm

# 2. Create .txth sidecar file
echo -e "codec = PSX\nchannels = 2\nsample_rate = 44100\ninterleave = 0x100\nnum_samples = data_size" > M000_audio.adpcm.txth

# 3. Decode with vgmstream
vgmstream-cli -o M000_audio.wav M000_audio.adpcm
```

### Key Format Parameters

| Parameter | Value |
|-----------|-------|
| Audio Codec | PS2 SPU ADPCM (PSX 4-bit) |
| Sample Rate | 44,100 Hz |
| Channels | 2 (Stereo) |
| Interleave | 0x100 (256 bytes) |
| DSI Block Size | 0x40000 (262,144 bytes) |
| Audio Type Tag | -8192 (0xFFFFE000) |
| Video Type Tag | -16384 (0xFFFFC000) |
| Video Codec | MPEG-2, 512x448, 29.97fps |

---

## Disc Layout

```
Root/
  SYSTEM.CNF              - Boot config (BOOT2 = cdrom0:\SLUS_209.94;1)
  SLUS_209.94             - 1.8 MB, main executable (ELF)
  CDDATA.DIG              - 261 MB, main data archive
  DATA0                   - 16 MB, all zeros (runtime scratchpad)
  IOPRP254.IMG            - IOP replacement image
  LIBSD.IRX               - Sound library driver
  MUS.IRX                 - Music/audio driver (custom)
  MCMAN.IRX               - Memory card manager
  MCSERV.IRX              - Memory card server
  MODHSYN.IRX             - Hardware synth module
  MODMIDI.IRX             - MIDI module
  MODMSIN.IRX             - MIDI single module
  PADMAN.IRX              - Controller driver
  SIO2MAN.IRX             - SIO2 manager
  DSI/
    M000.DSI              -  64 MB (opening cutscene)
    M001.DSI              -  31 MB
    M002.DSI              - 182 MB (largest)
    M003.DSI              -  36 MB
    M004.DSI              -  80 MB
    M005.DSI              -  61 MB
    M006.DSI              -  65 MB
    M008.DSI              -  34 MB
    M010.DSI              -  73 MB
    M014.DSI              -  60 MB
    M015.DSI              - 112 MB
    M016.DSI              -  47 MB
    M018.DSI              -  96 MB
    M021.DSI              - 116 MB
    M022.DSI              - 105 MB
    M023.DSI              - 209 MB
    M024.DSI              - 143 MB
    M025.DSI              - 123 MB
```

**Notes:**
- DSI numbering has gaps (no M007, M009, M011-M013, M017, M019-M020). These likely correspond to mission/chapter numbers.
- The executable contains cdrom paths to all DSI files, confirming they are loaded at runtime.
- DATA0 is entirely zeroed out and serves as a pre-allocated RAM buffer.

---

## DSI File Format

### Overview

DSI files are custom multiplexed streaming containers holding MPEG-2 video and PS2 ADPCM audio for cutscenes. The format is similar to Sony's PSS (PlayStation Stream System) but with a proprietary block header.

### Block Structure

Each file is divided into fixed **0x40000 (262,144 byte) blocks**.

```
Block N:
  +0x00  [32 bytes]  Block header
  +0x20  [32 bytes]  Padding (zeros)
  +0x40  [variable]  Stream 1 data
  +????  [variable]  Stream 2 data
```

Total blocks = file_size / 0x40000

### Block Header (32 bytes)

```
Offset  Size  Type    Field            Description
------  ----  ------  ---------------  -----------------------------------------
0x00    4     uint32  num_streams      Always 2
0x04    4     uint32  header_size      Always 64 (0x40)
0x08    4     int32   stream1_type     Type tag for stream 1
0x0C    4     uint32  stream1_size     Byte size of stream 1 data
0x10    4     uint32  stream2_offset   Byte offset of stream 2 within block
0x14    4     int32   stream2_type     Type tag for stream 2
0x18    4     uint32  stream2_size     Byte size of stream 2 data
0x1C    4     uint32  padding          Always 0
```

**Stream type tags:**
- **-8192** (0xFFFFE000) = ADPCM Audio
- **-16384** (0xFFFFC000) = MPEG-2 Video

**CRITICAL**: Audio and video streams **swap positions** between blocks. In most blocks, audio comes first (stream1_type = -8192). But in some blocks, video comes first (stream1_type = -16384). You MUST check the type tags for every block.

The swap pattern appears related to bitrate balancing - blocks with more video data put video first, blocks with more audio data put audio first.

### Audio Format

| Property | Value |
|----------|-------|
| Codec | PlayStation SPU ADPCM (4-bit) |
| Sample Rate | 44,100 Hz |
| Channels | 2 (Stereo) |
| Interleave | **0x100 (256 bytes)** |
| Bits per sample | 4 |
| ADPCM block size | 16 bytes = 28 samples |
| Samples per interleave chunk | 16 blocks x 28 = 448 samples |

The stereo interleave means: 256 bytes of left channel ADPCM, then 256 bytes of right channel ADPCM, repeating.

### Video Format

| Property | Value |
|----------|-------|
| Codec | MPEG-2 (Main Profile) |
| Resolution | 512 x 448 |
| Frame Rate | 29.97 fps |
| Aspect Ratio | 4:3 |
| Encoder | TMPGEnc ver. 2.58.44.152 |

The MPEG-2 sequence header (start code 0x000001B3) only appears in the first block's video stream. Subsequent blocks contain continuation data (raw MPEG-2 elementary stream, NOT Program Stream).

### ADPCM Technical Details

Each 16-byte ADPCM block produces 28 PCM samples:

```
Byte 0: [predict(4 high bits) | shift(4 low bits)]
Byte 1: flags (always 0x00 in DSI - no loop/end markers)
Bytes 2-15: 14 bytes of packed 4-bit samples (28 nibbles)
            Low nibble processed first, then high nibble
```

Prediction filter coefficients (fixed-point, denominator 64):

| Index | Coef 1 | Coef 2 |
|-------|--------|--------|
| 0 | 0 | 0 |
| 1 | 60 | 0 |
| 2 | 115 | -52 |
| 3 | 98 | -55 |
| 4 | 122 | -60 |

Decoding formula:
```python
sample = (sign_extended_nibble << 12) >> shift
sample = sample + ((hist1 * coef1 + hist2 * coef2 + 32) >> 6)
sample = clamp(sample, -32768, 32767)
hist2 = hist1
hist1 = sample
```

---

## CDDATA.DIG Format

### Overview

Self-contained archive (261 MB) where the file table and file data coexist in the same file. Contains 627 entries covering textures, models, sounds, and game data.

### File Table

- **Location**: First 5 sectors (bytes 0x0000 - 0x27FF, 10,240 bytes)
- **Entry count**: 627
- **Entry size**: 16 bytes each
- **Sector size**: 2048 bytes (standard CD-ROM sector)

### Entry Format (16 bytes, little-endian)

```
Offset  Size  Type    Field              Description
------  ----  ------  -----------------  ------------------------------------
0x00    4     uint32  sector_offset      Start sector (x2048 = byte offset)
0x04    4     uint32  compressed_size    Size on disc in bytes
0x08    2     uint16  sub_count          Sub-entry count or type indicator
0x0A    2     uint16  unknown            Always 1
0x0C    4     uint32  decompressed_size  Uncompressed data size
```

### Compression

- **Uncompressed** (202 entries): `compressed_size == decompressed_size`
- **Compressed** (425 entries): `compressed_size < decompressed_size`, ratio 1.3x - 3.2x
- Uses **Racjin compression algorithm** (9-bit token bitstream with context-sensitive sliding window)
- Decompression function in executable at virtual address **0x00263EF0**
- All 627 entries successfully decompressed. See [CDDATA.DIG Compression](#cddatadig-compression--racjin-algorithm-solved) section for details.

### Known Content Types

- **SCEI containers**: Uncompressed entries containing Sony standard asset containers (identified by "SCEI" + "SCEIVers"/"SCEIHead" signatures at offset 48)
- **sub_count = 1**: 416 entries, single assets
- **sub_count = 2-30+**: Multi-part entries (cutscene-related data, large asset packs)
- **sub_count = 141**: Single entry (#432), extremely large

### Data Layout

Entries are stored sequentially, sector-aligned with small padding gaps. The archive has near-100% space utilization (last entry ends at byte 261,108,264 of 261,109,760).

---

## Extraction Walkthrough

### Extracting Cutscene Audio from a DSI File

```python
import struct

def extract_dsi_audio(dsi_path, output_path):
    """Extract raw ADPCM audio from a DSI file."""
    AUDIO_TAG = -8192
    BLOCK_SIZE = 0x40000

    with open(dsi_path, 'rb') as f:
        import os
        file_size = os.path.getsize(dsi_path)
        num_blocks = file_size // BLOCK_SIZE
        all_audio = bytearray()

        for blk in range(num_blocks):
            f.seek(blk * BLOCK_SIZE)
            hdr = f.read(32)
            fields = struct.unpack('<IIiIIiII', hdr)
            # fields: num_streams, hdr_size, type1, size1, off2, type2, size2, pad
            type1, size1, off2, type2, size2 = fields[2], fields[3], fields[4], fields[5], fields[6]

            if type1 == AUDIO_TAG:
                f.seek(blk * BLOCK_SIZE + 64)
                all_audio.extend(f.read(size1))
            else:
                f.seek(blk * BLOCK_SIZE + off2)
                all_audio.extend(f.read(size2))

    with open(output_path, 'wb') as f:
        f.write(all_audio)

    # Write companion TXTH file for vgmstream
    with open(output_path + '.txth', 'w') as f:
        f.write("codec = PSX\n")
        f.write("channels = 2\n")
        f.write("sample_rate = 44100\n")
        f.write("interleave = 0x100\n")
        f.write("num_samples = data_size\n")

    return len(all_audio)
```

### Extracting Cutscene Video from a DSI File

```python
def extract_dsi_video(dsi_path, output_path):
    """Extract raw MPEG-2 video ES from a DSI file."""
    VIDEO_TAG = -16384
    BLOCK_SIZE = 0x40000

    with open(dsi_path, 'rb') as f:
        import os
        file_size = os.path.getsize(dsi_path)
        num_blocks = file_size // BLOCK_SIZE
        all_video = bytearray()

        for blk in range(num_blocks):
            f.seek(blk * BLOCK_SIZE)
            hdr = f.read(32)
            fields = struct.unpack('<IIiIIiII', hdr)
            type1, size1, off2, type2, size2 = fields[2], fields[3], fields[4], fields[5], fields[6]

            if type1 == VIDEO_TAG:
                f.seek(blk * BLOCK_SIZE + 64)
                all_video.extend(f.read(size1))
            else:
                f.seek(blk * BLOCK_SIZE + off2)
                all_video.extend(f.read(size2))

    with open(output_path, 'wb') as f:
        f.write(all_video)

    return len(all_video)
```

### Decoding with vgmstream

```bash
# Install vgmstream (macOS)
brew install vgmstream

# Decode to WAV
vgmstream-cli -o output.wav input.adpcm

# Check metadata without decoding
vgmstream-cli -m input.adpcm
```

### Muxing Video + Audio with ffmpeg

```bash
# Combine extracted video and decoded audio into a playable file
ffmpeg -i video.m2v -i audio.wav -c:v copy -c:a aac -shortest output.mp4
```

---

## Reverse Engineering Process

### Step 1: Initial Survey

We started by listing all files on the disc and examining their headers with hex dumps. Key observations:
- `SYSTEM.CNF` identified the executable as SLUS_209.94
- `DATA0` was all zeros (runtime buffer, not interesting)
- `CDDATA.DIG` had a structured table at the start — a file table
- DSI files had a repeating structure with recognizable patterns
- IOP modules (`.IRX` files) revealed the audio subsystem: LIBSD, MUS, MODHSYN, MODMIDI

### Step 2: CDDATA.DIG Table Analysis

By interpreting the first bytes of CDDATA.DIG as arrays of uint32 (little-endian), we found:
- 16-byte entries where field[0] was a sector offset (values * 2048 matched sequential byte offsets)
- Consecutive entries pointed to adjacent regions with small gaps (sector alignment padding)
- The table occupied exactly 5 sectors (10,240 bytes) = 640 entry slots, with 627 valid entries
- Field comparison: when field[1] (compressed) == field[3] (decompressed), data was uncompressed

### Step 3: DSI Header Discovery

DSI files showed a repeating pattern at 0x40000-byte intervals. By parsing the first 32 bytes as uint32:
- Field 0 = 2 (two streams)
- Field 1 = 64 (header size)
- Fields 2 and 5 were signed negative values (-8192 and -16384)
- Fields 3 and 6 were sizes that, when summed, fit within the block

We initially thought fields 2 and 5 were audio parameters (sample rate, volume). The breakthrough came when we noticed the MPEG-2 sequence header (0x000001B3) appeared at the offset pointed to by the stream with type -16384.

### Step 4: Stream Type Identification

Searching for MPEG start codes in the data confirmed:
- Offset after stream 1 (when type1 = -8192): No MPEG signatures = ADPCM audio
- Offset after stream 2 (when type2 = -16384): MPEG-2 sequence header found = video
- The "encoded by TMPGEnc" user data string in the MPEG stream provided extra confirmation

### Step 5: Stream Swapping Discovery

Some blocks had `total_size < audio_size`, which was impossible. Examining these blocks revealed the type tags were swapped:
- Normal blocks: type1=-8192 (audio first), type2=-16384 (video second)
- Swapped blocks: type1=-16384 (video first), type2=-8192 (audio second)

This was confirmed by checking actual data content at both positions.

### Step 6: ADPCM Decoding Attempts

We wrote a custom PS2 ADPCM decoder. The first attempt had a **critical Python operator precedence bug**:

```python
# WRONG (Python evaluates + before >>):
s = s + (hist1 * f0 + hist2 * f1 + 32) >> 6

# CORRECT:
s = s + ((hist1 * f0 + hist2 * f1 + 32) >> 6)
```

This caused the prediction filter to malfunction completely, dividing all output by 64.

### Step 7: Duration Analysis

After fixing the decoder, the mono output was 142.2 seconds at 44100Hz — exactly 2x the ~71-second video. This confirmed the data was stereo (two interleaved channels).

### Step 8: Stereo Interleave Discovery

We tried many interleave sizes:
- Half-split (first half = L, second half = R): Duration matched but audio had noise during silent sections
- 16-byte interleave: Duration matched but sounded "like a blown speaker"
- **256-byte (0x100) interleave**: Correct!

The final confirmation came from using vgmstream with a TXTH descriptor file, testing interleave values of 0x10, 0x20, 0x80, 0x100, 0x200, 0x400, 0x800, 0x1000.

### Step 9: Reference Comparison

A YouTube video of the opening cutscene served as a reference. Key insights from comparison:
- The YouTube video started with a Square Enix logo (silent) that was NOT part of M000.DSI
- The mono vgmstream decode sounded correct but at half speed, confirming stereo
- Duration matching: stereo at 44100Hz = 71.1 seconds, matching the ~72-second video

---

## Key Decisions & Breakthroughs

### 1. Recognizing the file table in CDDATA.DIG
The first field being small ascending integers (sector offsets) and the second field being sizes that, when added to the offset, approximately equaled the next entry's offset, was the giveaway.

### 2. Finding MPEG start codes to identify video vs audio streams
Instead of guessing what the negative type tags meant, scanning for the MPEG-2 sequence header (0x000001B3) in the data definitively identified which stream was video.

### 3. Discovering stream position swapping
The "impossible" case where total_size < audio_size led us to realize the streams swap positions. Without this, ~5% of blocks would have had their audio and video mixed up.

### 4. Using vgmstream instead of writing a custom decoder
After struggling with subtle decoder bugs, vgmstream provided a reference-quality decode. It confirmed our ADPCM decode was correct but allowed us to quickly test different interleave sizes.

### 5. The YouTube reference video
Comparing amplitude envelopes between our decode and the YouTube capture helped identify timing/duration issues and confirmed the Square Enix logo was a separate sequence.

### 6. Duration math to identify stereo
Mono at 44100Hz = 142.2s (2x the video). This simple calculation definitively proved the data was stereo, not mono at a higher sample rate.

### 7. Brute-forcing the interleave with vgmstream
Instead of trying to deduce the interleave from first principles, we generated WAV files for every common PS2 interleave size and listened to each one. The 0x100 (256-byte) interleave produced clean audio.

---

## Pitfalls & Lessons Learned

### Python operator precedence with bitwise shifts
`a + b >> c` evaluates as `(a + b) >> c`, not `a + (b >> c)`. This silent bug produced output that was partially recognizable but heavily distorted. Always use explicit parentheses with `>>` and `<<`.

### Don't assume interleave from data patterns
We initially thought the data was half-split stereo because there was an apparent "reset" in ADPCM parameters at the midpoint of block 0's audio. This was a coincidence. The actual interleave (256 bytes) couldn't be deduced from data patterns alone.

### Stream positions are not fixed
Assuming audio always comes first in the block header would have produced corrupted output for ~5% of blocks. Always check the type tags.

### Duration is the best sanity check
When the decoded audio is 2x too long, it's almost certainly stereo being decoded as mono. When it's half as long as expected, you might be dropping every other channel.

### Use existing tools as references
vgmstream's decode exactly matched our custom decoder's output, confirming the algorithm was correct. The issue was always the stereo interleave, not the ADPCM math.

### YouTube captures have offsets
The YouTube reference video included menu/logo footage before the actual cutscene. This caused an ~8.8-second offset that initially confused our amplitude comparison.

---

## CDDATA.DIG Compression — Racjin Algorithm (SOLVED)

### Discovery

The compression was identified as the **Racjin compression algorithm**, a known format used by the developer Racjin across multiple PS2/PSP/Wii games. An existing open-source implementation exists:

- **Repository**: https://github.com/Raw-man/Racjin-de-compression
- **License**: GPL-3.0
- **Language**: C++
- **Explicitly supports**: Fullmetal Alchemist (PS2), Naruto games, Bleach, and others

The README even mentions FMA specifically: *"not the case in Fullmetal Alchemist and the Broken Angel, which has cddata.dig files that are structured like cfc.dig files"*

### Algorithm Summary

- **9-bit tokens** packed into a bitstream (read from LE uint16, shifted by variable bit_shift 0-7)
- **Bit 8** = flag: 1 = literal byte, 0 = back-reference
- **Literal**: lower 8 bits stored directly to output
- **Reference**: bits 3-7 = 5-bit frequency index, bits 0-2 = 3-bit length (+1, max 8 bytes)
- Uses a **context-sensitive sliding window**: 8192-entry table indexed by `(frequency_index + last_decoded_byte * 32)`
- A 256-entry frequency counter wraps at 31 (`& 0x1F`)

### Decompression function location in executable

Virtual address: **0x00263EF0** (file offset 0x163F70)

### Python Implementation

```python
def racjin_decompress(buffer, decompressed_size):
    index = 0
    dest_index = 0
    last_dec_byte = 0
    bit_shift = 0
    frequencies = [0] * 256
    seq_indices = [0] * 8192
    output = bytearray(decompressed_size)

    while index < len(buffer) - 1 and dest_index < decompressed_size:
        next_code = buffer[index + 1] << 8 | buffer[index]
        next_code = next_code >> bit_shift
        bit_shift += 1
        index += 1
        if bit_shift == 8:
            bit_shift = 0
            index += 1

        seq_index = dest_index

        if (next_code & 0x100) != 0:
            output[dest_index] = next_code & 0xFF
            dest_index += 1
        else:
            key = ((next_code >> 3) & 0x1F) + last_dec_byte * 32
            src_index = seq_indices[key]
            length = (next_code & 0x07) + 1
            for _ in range(length):
                if dest_index >= decompressed_size: break
                output[dest_index] = output[src_index]
                dest_index += 1
                src_index += 1

        if dest_index >= decompressed_size: break
        key = frequencies[last_dec_byte] + last_dec_byte * 32
        seq_indices[key] = seq_index
        frequencies[last_dec_byte] = (frequencies[last_dec_byte] + 1) & 0x1F
        last_dec_byte = output[dest_index - 1]

    return bytes(output)
```

### Result

All 627 entries decompressed successfully with zero failures.

---

## CDDATA.DIG Content Map

After decompression, the 627 entries contain:

### Raw PS2 ADPCM Audio (57 files)

These start directly with valid ADPCM blocks and use the **same format as DSI audio**: stereo, 44100Hz, 0x100 interleave.

| Entry Range | Count | Content | Total Duration |
|-------------|-------|---------|----------------|
| 0235-0238 | 4 | **Music tracks** (0237 = credits song) | 10.4 min |
| 0240-0290 | 51 | **Voice lines** (confirmed working) | 7.3 min |
| 0074, 0239 | 2 | Short clips | ~1.3s |

To decode: save as `.adpcm`, add `.txth` sidecar, run `vgmstream-cli`.

### Asset Containers (204 files)

Header: `00000000 <content_size> 10000000 00000000`

Contain section tables pointing to SCEI-formatted assets (textures, 3D models). Not audio.

### Multi-Section Containers with Sound Banks (entries ~0433-0577)

These use a sub-entry table format:
```
Repeating 16-byte entries:
  uint32  index       Sequential (0, 1, 2, ...)
  uint32  size        Sub-entry data size
  uint32  offset      Byte offset within file
  uint32  padding     0
```

The **largest sub-entry** in each container appears to be a sound bank with its own header:
```
uint32  sound_count
uint32  data_offset     (offset to audio data, i.e., header size)
[metadata entries per sound — format not fully decoded]
[raw PS2 ADPCM audio data]
```

These contain **combat voice barks** embedded alongside 3D model/animation data. The audio format within these containers is proprietary and does not match any known PS2 audio codec. See [Complete Changelog of Attempts](#complete-changelog-of-attempts) for full details on extraction efforts.

### SCEI Containers (156 files)

Sony Computer Entertainment standard format with "SCEIVers"/"SCEIHead" markers. Asset data (not audio).

### Other/Unknown (20 files)

Small files with unidentified formats.

---

## Extraction Results Summary

### USA Version (SLUS_209.94)

| Source | Files | Duration | Status |
|--------|-------|----------|--------|
| DSI cutscene audio | 18 WAV | ~30 min | Fully extracted |
| DSI cutscene video | 18 M2V | ~30 min | Fully extracted |
| CDDATA.DIG voice lines (0240-0290) | 51 WAV | 7.3 min | Fully extracted |
| CDDATA.DIG music (0235-0238) | 4 WAV | 10.4 min | Fully extracted |
| CDDATA.DIG other SFX (0191-0234) | 44 WAV | ~14.7 min | Fully extracted (hidden SFX found via lookup table) |
| **USA Total** | **399 files** | **62.4 min** | **Complete** |

### JP Version (SLPS_254.12)

| Source | Files | Duration | Status |
|--------|-------|----------|--------|
| DSI cutscene audio | 18 WAV | ~30 min | Fully extracted |
| CDDATA.DIG voice lines (0406-0456) | 51 WAV | 7.3 min | Fully extracted |
| CDDATA.DIG music (33, 380, 401) | 3 WAV | ~6 min | Fully extracted |
| CDDATA.DIG other SFX (various) | 44 WAV | ~14 min | Fully extracted |
| **JP Total** | **310 files** | **57.3 min** | **Complete** |

### USA <-> JP Audio Correspondence

All audio in both versions has been fully extracted and accounted for. The 101-entry lookup table in both executables provides exact 1:1 mapping (see [USA <-> JP Entry Mapping](#usa--jp-entry-mapping) section).

### Undub ISO Status (FMA_Undub.iso) — v3.0 COMPLETE

| Component | Status |
|-----------|--------|
| DSI cutscene audio (18/18) | Replaced with JP audio ✓ |
| CDDATA.DIG lookup table (101 entries) | All replaced ✓ |
| CDDATA.DIG SCEI hash-matched banks (85 entries) | All replaced ✓ |
| CDDATA.DIG voice-only banks (12 entries) | All replaced ✓ (includes Edward's combat grunts) |
| **Total CDDATA.DIG entries replaced** | **198** |
| Truncated entries | 56 of 198 (slightly shorter at end) |
| Perfect-fit entries | 142 of 198 |

The undub ISO was built by patching the original USA ISO in-place (preserving PS2 boot sector) using pycdlib for file location lookup. The undub.py tool handles DSI + CDDATA patching with truncation for oversized JP entries. Edward's Japanese combat grunts confirmed working in PCSX2. Note: save states from unpatched version won't work -- must use memory card saves or start fresh.

### Output Directories

```
extracted_audio/          - DSI cutscene audio (WAV + raw ADPCM + TXTH)
extracted_video/          - DSI cutscene video (M2V)
extracted_cddata/         - All 627 decompressed CDDATA.DIG entries (BIN)
extracted_cddata_audio/   - Decoded audio from CDDATA.DIG (WAV)
```

---

## Complete Game Asset Map

### CDDATA.DIG Content (627 entries, 357 MB decompressed)

| Asset Type | Entries | Files | Size | Format | Status |
|------------|---------|-------|------|--------|--------|
| Standalone audio | 74, 235-290 | 57 | 51 MB | Stereo PSX ADPCM 44.1kHz, 0x100 interleave | Fully decoded |
| SCEI sound banks | 78-234 | 156 | 21 MB | SCEIVers/SCEIVagi/SCEISets/SCEIMidi headers + mono PSX ADPCM 22kHz samples in BD section | Fully decoded, 1,604 samples extracted |
| Level graphics | 2-57, 291-431 | 203 | 43 MB | 2-section containers: Section 0 = material/shader params, Section 1 = PS2 GS native data (vertices, textures, PRIM/RGBAQ/XYZ2/TEX0 registers) | Structure identified |
| Combat data packs | 433-577 | 144 | 208 MB | Multi-sub containers with: sound banks (130MB), 3D indexed data (60MB), float/transform matrices (<1MB), AI/gameplay config (<2MB) | Structure identified |
| Shared game data | 0-1, 58-73, 75, 432 | 67 | 34 MB | Multi-sub containers: character models, UI, common assets | Structure identified |

### DSI Files (18 files, ~1.8 GB)
- Video: MPEG-2, 512x448, 29.97fps (TMPGEnc encoded)
- Audio: Stereo PSX ADPCM, 44.1kHz, 0x100 interleave, block-multiplexed with video

### SCEI Sound Bank Format (CRACKED)
- Header chunks: SCEIVers (version), SCEIVagi (sample index), SCEISets (instrument groups), SCEIMidi (sequences)
- Vagi chunk structure: count(4) + (count+1)*4 offset table + count*8 parameter blocks
- Parameter block: BD_offset(4) + metadata(4)
- BD data (Section 1): Raw mono PS2 SPU ADPCM samples at 22,050 Hz concatenated sequentially
- USA: 1,604 samples from 141 banks; JP: 1,603 samples from 141 banks

---

## Reverse Engineering Process

### Steps 1-9: DSI Format (see above)

### Step 10: CDDATA.DIG Decompression

After cracking the DSI format, we turned to CDDATA.DIG. Initial analysis showed 425 of 627 entries were compressed with an unknown algorithm (data started with `00 05` or `00 07`).

We searched the executable for the decompression routine by finding cross-references to the CDDATA.DIG string, then tracing MIPS code for typical decompression patterns (bitstream reading, flag-based literal/reference branching, output buffer copy loops).

The decompression function was found at **0x00263EF0**. Its structure matched the known **Racjin compression** algorithm, which had already been reverse engineered and published on GitHub. We ported the C++ implementation to Python and successfully decompressed all 627 entries.

### Step 11: Content Identification

After decompression, we categorized files by examining headers:
- Files starting with valid ADPCM blocks (shift 0-12, predict 0-4, flag 0-7 across 32+ consecutive blocks) → raw audio
- Files starting with `00000000 XXXXXXXX 10000000` → asset containers
- Files with sequential index tables → multi-section containers

### Step 12: Audio Format Confirmation

We tested the raw ADPCM files with vgmstream using the same parameters as DSI audio (stereo, 44100Hz, 0x100 interleave). The credits song (entry 0237) was immediately recognizable. Voice line entries 0240-0290 were confirmed correct by the user.

### Step 13: Sound Bank Discovery

The larger container files (0433-0577) contain sound banks — sub-entries with an internal header listing multiple sounds. The audio body is raw ADPCM but can't be decoded as a single stream because it contains multiple concatenated clips. The per-clip offset table in the sound bank header needs to be parsed to extract individual voice lines.

### Step 14: SCEI Sound Bank Cracking
- Identified "IECSigaV" (SCEIVagi) markers in SCEI container entries (78-234)
- Discovered these are HD/BD-style sound banks: Vagi chunk = instrument header, Section 1 = raw ADPCM sample data
- Parsed Vagi parameter blocks to find BD offsets for each sample
- Key insight: parameter blocks start at offset 4 + (count+1)*4 in the Vagi data, each 8 bytes (4 bytes BD offset + 4 bytes metadata)
- Successfully extracted 1,604 USA and 1,603 JP individual samples as mono 22050Hz PSX ADPCM

### Step 15: Level Data Identification
- Found PS2 GS (Graphics Synthesizer) register patterns (PRIM, RGBAQ, XYZ2, TEX0, SCISSOR) in Section 1 of 2-section containers
- Confirmed these are raw PS2 GPU rendering data: vertices, textures, polygon definitions
- Section 0 contains material/shader parameters with color values and float multipliers

### Step 16: Combat Container Sub-entry Classification
- Categorized all sub-entries across 144 combat containers by first uint32 value and size patterns
- Sound banks (130MB): same format as SCEI Vagi, with 3-49 sounds each
- Indexed data blocks (60MB): 3D model vertices, animations, collision meshes
- Float matrices (<1MB): camera positions, transform matrices
- Small config data (<2MB): AI parameters, state machines, gameplay logic

### Step 17: SCEI Sample Hash Matching
- Hashed all 1,604 USA and 1,603 JP ADPCM samples (MD5 of raw ADPCM data)
- 1,386 samples matched (identical SFX shared between versions)
- 218 USA-only samples identified as English voice content
- 217 JP-only samples identified as Japanese voice replacements
- Shared samples used to map 85 previously unmapped SCEI banks (entries 78-190) to their JP equivalents
- Key insight: banks with shared SFX + different voice samples must be the same bank in different languages

### Step 18: Voice-Only Bank Matching
- 27 SCEI banks had zero hash matches (100% voice content, no shared SFX)
- 15 had 0 samples (metadata only, no replacement needed)
- 12 with voice samples matched to JP banks by sample count + file size proximity
- USA entries 105, 107, 108 (3 samples each) -> JP 491 -- confirmed as Edward's combat grunts!
- USA 141-143, 146, 151-153, 156-157 -> various JP banks -- other character voice banks

### Step 19: Final Patch Build (v3.0)
- 198 total CDDATA.DIG entries patched (101 lookup table + 85 hash-matched + 12 voice-only)
- 18 DSI cutscene files patched
- 142 entries fit perfectly, 56 truncated to fit ISO slots
- xdelta3 patch generated (93MB), verified round-trip
- Published to GitHub as v3.0 release
- User confirmed: Edward's Japanese combat grunts working in PCSX2

### Step 20: Cutscene Subtitle Generation
- Used OpenAI Whisper (small model) to transcribe English cutscene audio to SRT
- Key discovery: extracted audio is ~8.9% longer than video due to DSI block padding accumulation
- Solution: squeeze audio with ffmpeg atempo filter (factor ~1.0886) before transcription
- This ensures subtitle timestamps match video perfectly

### Step 21: Subtitle Correction & Formatting
- Converted SRT to ASS with anime-style formatting (Crunchyroll-like: Arial bold, white, black outline 2.5px)
- Manual corrections across all 18 cutscenes:
  - Character names: Armini -> Armony (Armony Eiselstein), Edward Eric -> Edward Elric
  - Ed's classic short rants restored (Whisper garbled these)
  - Merged speaker lines split into separate subtitle entries
  - Armstrong's verbose dialogue cleaned up
  - Professor name: Aselstein -> Eiselstein
- Waveform verification: RMS envelope analysis flagged subtitles during silence (false timing) and overly long durations
- Fixed M010 and M014 using speech onset detection to tighten subtitle windows

### Step 22: Final Cutscene Video Build
- All 18 cutscenes built as MKV: original PS2 video + squeezed JP audio + corrected English ASS subtitles
- VideoToolbox H.264 hardware acceleration on Apple Silicon
- Soft subtitles (ASS track) for rendering in VLC/media players
- 511MB total output in output/cutscene_final/

---

## Key Decisions & Breakthroughs

### 1-7: DSI Format (see above)

### 8. Finding the Racjin decompression algorithm
Searching the executable's MIPS code for the decompression routine led us to function 0x263EF0, which matched the Racjin compression pattern. The existing GitHub implementation confirmed the match and provided a ready-made solution.

### 9. Universal audio format discovery
Testing the credits song (entry 0237) with the same stereo 44100Hz 0x100 interleave parameters as DSI audio proved that ALL audio in the game uses the identical format. This eliminated the need to figure out audio parameters per-file.

### 10. Strict ADPCM validation
Initial loose ADPCM detection (checking only 4 blocks) produced false positives. Tightening to 32 consecutive blocks with strict predict<=4, flag<=7, shift<=12 filtering reduced 217 candidates to 57 genuine audio files.

### 11. Sample hash matching for bank mapping
Instead of trying to match banks by position or structure, hashing individual ADPCM samples revealed which banks correspond between versions. Identical SFX samples (footsteps, explosions) served as "anchors" linking USA banks to JP banks.

### 12. Voice-only bank matching by sample count
When hash matching found zero shared samples (100% voice content), matching by sample count + file size identified the remaining banks. This caught Edward's combat grunt bank (entries 105/107/108).

### 13. Save states bypass disc reads
User initially couldn't hear changes because PCSX2 save states capture audio already in memory. Loading from memory card saves or starting fresh forces the game to read patched data from disc.

### 14. Audio tempo sync for subtitle timing
The DSI block extraction produces audio ~8.9% longer than video because SPU2 padding accumulates when blocks are concatenated. Squeezing the audio with atempo=1.0886 before transcription ensures Whisper timestamps match video frames perfectly.

---

## Pitfalls & Lessons Learned

### (Previous lessons 1-6 still apply)

### Loose format detection creates false positives
Checking only a few bytes for ADPCM validity flagged hundreds of non-audio files. Many data formats happen to have bytes in the 0-4 range at 16-byte intervals. Always validate across many blocks and cross-reference with file size / expected duration.

### Container files are not raw audio
The decompressed container files (0433-0577) superficially passed ADPCM checks because their sub-entry table happened to have valid-looking first bytes. But the actual content starts at an offset after the container header. Always check for container structure before assuming raw format.

### Same codec everywhere simplifies everything
Once we confirmed the audio format for DSI files, the same parameters worked for CDDATA.DIG audio. When reverse engineering a game, test the known-good format on all unknown audio before trying other parameters.

---

## USA <-> JP Entry Mapping

### 101-Entry Lookup Table

Both the USA executable (SLUS_209.94) and the JP executable contain a 101-entry lookup table that provides the exact 1:1 mapping between CDDATA.DIG entries across versions. Both tables use the same index, meaning index N in the USA table and index N in the JP table refer to the same sound/asset ID.

**Table locations in executables:**
- **USA**: file offset 0x1B612E
- **JP**: file offset 0x1B52EE

### Categorization

| Index Range | Count | Category | USA Entries | JP Entries |
|-------------|-------|----------|-------------|------------|
| 0-44 | 45 | Other SFX/assets | 191-234 | Various (17-628) |
| 45-47 | 3 | Music | 235-237 | 33, 380, 401 |
| 48 | 1 | Unknown | 238 | (unknown) |
| 49-99 | 51 | Voice/SFX | 240-290 | 406-456 |
| 100 | 1 | Extra | (extra entry) | (extra entry) |

### Full Mapping Table

| Index | USA Entry | JP Entry | Category |
|-------|-----------|----------|----------|
| 0 | 191 | 17 | SFX |
| 1 | 192 | 18 | SFX |
| 2 | 193 | 19 | SFX |
| 3 | 194 | 20 | SFX |
| 4 | 195 | 21 | SFX |
| 5 | 196 | 22 | SFX |
| 6 | 197 | 23 | SFX |
| 7 | 198 | 24 | SFX |
| 8 | 199 | 25 | SFX |
| 9 | 200 | 26 | SFX |
| 10 | 201 | 27 | SFX |
| 11 | 202 | 28 | SFX |
| 12 | 203 | 29 | SFX |
| 13 | 204 | 30 | SFX |
| 14 | 205 | 31 | SFX |
| 15 | 206 | 32 | SFX |
| 16 | 207 | 374 | SFX |
| 17 | 208 | 375 | SFX |
| 18 | 209 | 376 | SFX |
| 19 | 210 | 377 | SFX |
| 20 | 211 | 378 | SFX |
| 21 | 212 | 379 | SFX |
| 22 | 213 | 383 | SFX |
| 23 | 214 | 384 | SFX |
| 24 | 215 | 385 | SFX |
| 25 | 216 | 386 | SFX |
| 26 | 217 | 387 | SFX |
| 27 | 218 | 388 | SFX |
| 28 | 219 | 389 | SFX |
| 29 | 220 | 390 | SFX |
| 30 | 221 | 391 | SFX |
| 31 | 222 | 392 | SFX |
| 32 | 223 | 393 | SFX |
| 33 | 224 | 394 | SFX |
| 34 | 225 | 395 | SFX |
| 35 | 226 | 396 | SFX |
| 36 | 227 | 397 | SFX |
| 37 | 228 | 398 | SFX |
| 38 | 229 | 399 | SFX |
| 39 | 230 | 400 | SFX |
| 40 | 231 | 624 | SFX |
| 41 | 232 | 625 | SFX |
| 42 | 233 | 626 | SFX |
| 43 | 234 | 627 | SFX |
| 44 | 234 | 628 | SFX |
| 45 | 235 | 33 | Music |
| 46 | 236 | 380 | Music |
| 47 | 237 | 401 | Music |
| 48 | 238 | — | Unknown |
| 49 | 240 | 406 | Voice/SFX |
| 50 | 241 | 407 | Voice/SFX |
| 51 | 242 | 408 | Voice/SFX |
| 52 | 243 | 409 | Voice/SFX |
| 53 | 244 | 410 | Voice/SFX |
| 54 | 245 | 411 | Voice/SFX |
| 55 | 246 | 412 | Voice/SFX |
| 56 | 247 | 413 | Voice/SFX |
| 57 | 248 | 414 | Voice/SFX |
| 58 | 249 | 415 | Voice/SFX |
| 59 | 250 | 416 | Voice/SFX |
| 60 | 251 | 417 | Voice/SFX |
| 61 | 252 | 418 | Voice/SFX |
| 62 | 253 | 419 | Voice/SFX |
| 63 | 254 | 420 | Voice/SFX |
| 64 | 255 | 421 | Voice/SFX |
| 65 | 256 | 422 | Voice/SFX |
| 66 | 257 | 423 | Voice/SFX |
| 67 | 258 | 424 | Voice/SFX |
| 68 | 259 | 425 | Voice/SFX |
| 69 | 260 | 426 | Voice/SFX |
| 70 | 261 | 427 | Voice/SFX |
| 71 | 262 | 428 | Voice/SFX |
| 72 | 263 | 429 | Voice/SFX |
| 73 | 264 | 430 | Voice/SFX |
| 74 | 265 | 431 | Voice/SFX |
| 75 | 266 | 432 | Voice/SFX |
| 76 | 267 | 433 | Voice/SFX |
| 77 | 268 | 434 | Voice/SFX |
| 78 | 269 | 435 | Voice/SFX |
| 79 | 270 | 436 | Voice/SFX |
| 80 | 271 | 437 | Voice/SFX |
| 81 | 272 | 438 | Voice/SFX |
| 82 | 273 | 439 | Voice/SFX |
| 83 | 274 | 440 | Voice/SFX |
| 84 | 275 | 441 | Voice/SFX |
| 85 | 276 | 442 | Voice/SFX |
| 86 | 277 | 443 | Voice/SFX |
| 87 | 278 | 444 | Voice/SFX |
| 88 | 279 | 445 | Voice/SFX |
| 89 | 280 | 446 | Voice/SFX |
| 90 | 281 | 447 | Voice/SFX |
| 91 | 282 | 448 | Voice/SFX |
| 92 | 283 | 449 | Voice/SFX |
| 93 | 284 | 450 | Voice/SFX |
| 94 | 285 | 451 | Voice/SFX |
| 95 | 286 | 452 | Voice/SFX |
| 96 | 287 | 453 | Voice/SFX |
| 97 | 288 | 454 | Voice/SFX |
| 98 | 289 | 455 | Voice/SFX |
| 99 | 290 | 456 | Voice/SFX |
| 100 | — | — | Extra |

### Key Observations

- **SFX entries 0-15** (USA 191-206 -> JP 17-32): Sequential mapping, both sides contiguous.
- **SFX entries 16-39** (USA 207-230 -> JP 374-400): USA is contiguous but JP jumps from 379 to 383 (skipping 380-382, which are music/other).
- **SFX entries 40-44** (USA 231-234 -> JP 624-628): Maps to the very end of the JP archive.
- **Music entries 45-47**: Non-contiguous in JP (33, 380, 401) -- scattered across the archive.
- **Voice/SFX entries 49-99**: Clean contiguous block in both versions (USA 240-290 -> JP 406-456).

---

## Combat Voice Audio (Unsolved)

### Structure Mismatch Between Versions

USA combat containers (CDDATA.DIG entries 501-573, 57-67) bundle voice audio with 3D model/animation data in multi-section format. The JP version has a fundamentally different structure -- the same entry numbers are either empty or much smaller.

**Sub-entry analysis example:** USA entry 67 has 17 sub-entries (1.8MB total), while JP entry 67 has 1 sub-entry (201KB). The USA containers embed sound banks alongside 3D data; the JP containers contain only the base data.

### Sound Bank False Positives

3D float data within these containers passes ADPCM validation because shift/predict/flag bytes happen to fall within the valid range. Careful parsing is needed to separate genuine audio from 3D geometry data that coincidentally looks like valid ADPCM.

### Cross-Version References

A 7-entry mapping table exists in both executables:
- **USA** at offset 0x1BE5B8: references entries [86, 102, 117, 75, 117, 75, 199]
- **JP** at offset 0x1BCD78: references entries [162, 249, 131, 110, 78, 68, 21]

### Audio Clip Counts

- **42 USA combat audio clips** found in sound bank sub-entries across containers
- **100 JP combat audio clips** found across different containers
- No automated matching is possible due to completely different data organization between versions

---

## Complete Changelog of Attempts

### What we tried for combat audio

1. Standard PS2 SPU ADPCM with stereo 44100Hz 0x100 interleave (same as working audio) -- static
2. Mono at 22050/44100/48000Hz -- static for USA, works for JP embedded clips
3. Stereo with interleave 0x10, 0x20, 0x80, 0x100, 0x200, 0x400, 0x800 -- all static
4. PCM16 little-endian -- static
5. PCM16 big-endian -- static
6. PSX_bf (bad flags ADPCM variant) -- static
7. Brute-force scanning for ADPCM regions in containers -- found false positives (3D float data)
8. Strict ADPCM validation (32+ consecutive blocks, non-zero data check) -- found only SFX, no voice
9. Relaxed validation (allowing sparse data) -- 73 USA clips extracted, all static
10. Sound bank header parsing (count + header_size + entries) -- found internal structure but audio at parsed offsets was static
11. Per-clip header skipping (84-byte headers with float parameters) -- data after header still static
12. Sub-sound entry parsing (154 entries within sound 0 of entry 501) -- all static
13. Binary diff comparing USA entry 67 (17 sub-entries, 2MB) vs JP entry 67 (1 sub-entry, 200KB) -- completely different structures
14. Searching for SCEI/VAGI/HD/BD signatures in containers -- none found
15. Executable code tracing (function at 0x0024D460 loads entries, buffer at 0x2D1590) -- identified loading path but not format
16. MODHSYN synthesizer module analysis -- found "Vagi" string but containers don't use standard HD/BD format
17. Size-matching USA entries to JP entries by decompressed size -- 57 matches found but replacing them didn't fix combat audio (wrong assumption)

### Key discovery about JP combat audio

- JP embedded clips decode correctly as **mono 44.1kHz** PS2 ADPCM (not stereo!)
- JP containers have audio scattered across completely different entry numbers
- USA containers at same indices are either empty in JP or much smaller
- The USA localization restructured the entire archive, bundling voice audio into containers alongside 3D data

### Resolution: SCEI bank approach succeeded

The combat containers turned out to be a red herring for audio replacement. The actual combat voice audio (including Edward's grunts) is stored in **SCEI sound banks** (entries 78-190), not in the multi-section combat containers. Sample hash matching (Step 17) and voice-only bank matching (Step 18) successfully identified and replaced all combat voice banks, bypassing the proprietary container format entirely.

---

## What Remains

**Project essentially complete.** Undub patch v3.0 published and verified.

- Minor: 56 of 198 CDDATA entries truncated (some voice clips cut slightly short at the end).
- Minor: 1 USA sample in bank 154 has no JP equivalent.
- Note: Save states from unpatched version won't work -- must use memory card saves or start fresh.

---

## Tools Used

| Tool | Purpose |
|------|---------|
| **Python 3** | Hex analysis, binary parsing, Racjin decompression, ADPCM decoder |
| **vgmstream** (`vgmstream-cli`) | PS2 ADPCM decoding, format identification. Install: `brew install vgmstream` |
| **ffmpeg/ffprobe** | MPEG-2 video analysis, audio format conversion. Install: `brew install ffmpeg` |
| **xxd** | Quick hex dumps of file headers |
| **TXTH format** | vgmstream's text-based header descriptor for headerless audio files |
| **Racjin-de-compression** | Reference C++ implementation. Clone: `git clone https://github.com/Raw-man/Racjin-de-compression.git` |
| **OpenAI Whisper** (small model) | Speech-to-text transcription for cutscene subtitles. Install: `pip install openai-whisper` |

### TXTH Template (works for ALL audio in this game)

```
codec = PSX
channels = 2
sample_rate = 44100
interleave = 0x100
num_samples = data_size
```

Save as `yourfile.adpcm.txth` alongside the raw `.adpcm` file and vgmstream will auto-detect it.

---

## Published Artifacts

| Artifact | Location | Description |
|----------|----------|-------------|
| **fma-broken-angel-undub v3.0** | GitHub: `soyjxck/fma-broken-angel-undub` | 93MB xdelta patch, README, apply script, technical docs |
| **racjin-python** | GitHub: `soyjxck/racjin-python` | Racjin compression/decompression Python library |
| **FMA_Undub.iso** | Local (1.8GB) | Complete undub ISO with JP cutscene + voice + combat grunt audio |
| **tools.py** | Local | Archive extraction and audio processing utilities |
| **undub.py** | Local | DSI + CDDATA patching tool with truncation support |
| **Subtitled cutscene videos** | Local: `output/cutscene_final/` (511MB) | 18 MKV files with JP audio + English ASS subtitles, Whisper-transcribed and manually corrected |
| **REVERSE_ENGINEERING_NOTES.md** | Local | Complete reverse engineering documentation |
