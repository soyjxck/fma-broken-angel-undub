# Fullmetal Alchemist and the Broken Angel — Undub Patch

Replaces English voice audio with Japanese voice audio in the USA release of **Fullmetal Alchemist and the Broken Angel** (PS2).

**[Download latest patch from Releases](https://github.com/soyjxck/fma-broken-angel-undub/releases/latest)**

## What's Changed

| Content | Status |
|---------|--------|
| Cutscene dialogue (18 FMVs, ~30 min) | Fully Japanese (v4.1: opening uses native JP video) |
| In-game voice lines & SFX (101 entries) | Fully Japanese |
| Music (4 tracks) | Japanese |
| Combat voice barks | Remains English* |
| Cutscene subtitles (18 MKVs) | English subs on JP audio (standalone files) |

\*Combat voice audio is stored in a proprietary format embedded within multi-purpose game data containers. See [TECHNICAL.md](TECHNICAL.md) for details.

## Requirements

- **USA ISO**: `Fullmetal Alchemist and the Broken Angel (USA).iso`
  - Expected size: 1,927,217,152 bytes
  - MD5: *(check your dump)*
- **xdelta3**: Patching tool ([download](https://github.com/marco-calautti/DeltaPatcher) for GUI, or install CLI)

## How to Apply

### Option A: GUI (DeltaPatcher — Windows/Mac/Linux)

1. Download [DeltaPatcher](https://github.com/marco-calautti/DeltaPatcher/releases)
2. Open DeltaPatcher
3. **Original file**: Select your USA ISO
4. **Patch file**: Select `FMA_Undub.xdelta`
5. Click **Apply patch**
6. Load the patched ISO in PCSX2

### Option B: Command Line

```bash
# Install xdelta3
# macOS: brew install xdelta
# Linux: apt install xdelta3
# Windows: download from https://github.com/jmacd/xdelta-gpl/releases

# Apply patch
xdelta3 -d -s "Fullmetal Alchemist and the Broken Angel (USA).iso" \
    FMA_Undub.xdelta \
    "FMA_Undub.iso"
```

### Option C: Python script

```bash
python3 apply_patch.py "Fullmetal Alchemist and the Broken Angel (USA).iso"
```

## Compatibility

- Tested with **PCSX2** (v1.7+/nightly and v2.x)
- Should work on modded PS2 hardware (untested)
- The patched ISO is byte-for-byte identical in size to the original

## How It Was Made

This patch was created by reverse engineering the game's archive formats:

1. **DSI cutscene files**: Custom multiplexed MPEG-2 video + PS2 ADPCM audio containers. Audio streams extracted, replaced with Japanese equivalents, and reinserted block-by-block.

2. **CDDATA.DIG archive**: 627-entry archive using Racjin compression. A 101-entry sound ID lookup table was found in both the USA and Japanese executables, providing exact 1:1 entry mapping. Japanese entries were decompressed, recompressed, and patched in-place.

3. **ISO patching**: Original ISO structure preserved — files replaced at their exact sector positions with boot sector intact.

See [TECHNICAL.md](TECHNICAL.md) for the complete reverse engineering documentation.

## Subtitled Cutscene Videos

In addition to the undub patch, 18 subtitled cutscene videos are available as standalone MKV files. These combine the original PS2 video with Japanese audio and English subtitles.

**Note**: These are provided separately from the xdelta patch -- subtitle tracks cannot be baked into the PS2 ISO since the game's DSI container format has no subtitle stream support. The MKVs are intended for reference and enjoyment outside of gameplay (e.g., watching cutscenes in VLC or any media player).

- **Format**: MKV with H.264 video, Japanese audio, and soft English ASS subtitles
- **Subtitles**: Transcribed from English audio using Whisper AI, then manually corrected for character names (Edward Elric, Armony Eiselstein, etc.) and dialogue accuracy
- **Styling**: Anime/Crunchyroll-style formatting (Arial bold, white text, black outline)
- **Total size**: 511MB (18 files)

## Known Limitations

- **Combat voice barks remain English**: These are embedded in large multi-purpose containers (entries 501-573) alongside 3D models and animations, using a proprietary format that couldn't be decoded through static analysis. The Japanese version stores combat data in a completely different structure, making automated mapping impossible.

- **Some voice/SFX entries truncated**: 56 of 101 audio entries had Japanese audio larger than the English originals. These were truncated to fit (typically 10-15% shorter). Most truncation affects the tail end of longer SFX compilations and is barely noticeable during gameplay.

## Credits

- Reverse engineering and patch creation: Built with Claude Code
- [Racjin-de-compression](https://github.com/Raw-man/Racjin-de-compression) by Raw-man — Reference C++ implementation of the Racjin compression algorithm
- [vgmstream](https://github.com/vgmstream/vgmstream) — Used for audio format verification
- [pycdlib](https://github.com/clalancette/pycdlib) — ISO filesystem analysis
- [OpenAI Whisper](https://github.com/openai/whisper) — Speech-to-text for cutscene subtitle generation

## License

This patch contains no copyrighted game data. It is a binary diff that requires the original USA ISO to apply. For personal use only.
