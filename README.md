# Fullmetal Alchemist and the Broken Angel — Undub Patch

Replaces English audio with Japanese audio in the USA PS2 release. Includes English subtitles on cutscenes.

If this helped you, consider [buying me a coffee](https://ko-fi.com/soyjack)

## What's Changed

| Content | Status |
|---------|--------|
| Cutscene dialogue (18 FMVs) | Japanese audio + English subtitles |
| Opening cutscene | Full JP video + audio + subtitles |
| In-game voice/SFX | Japanese (per-sample replacement) |
| Combat voice barks | Japanese (force-fit resampling for oversized samples) |
| Oversized JP voice samples | Resampled to fit (via psxavenc) |
| Menu sound effects | Preserved (not replaced) |
| Music | Unchanged |

## How to Patch

### Option 1: xdelta (recommended)

Pre-built patch. No build tools needed.

**Requirements**: USA ISO + [DeltaPatcher](https://github.com/marco-calautti/DeltaPatcher/releases)

1. Download `FMA_Undub.xdelta` from [Releases](https://github.com/soyjxck/fma-broken-angel-undub/releases/latest)
2. Open DeltaPatcher
3. **Original file**: `Fullmetal Alchemist and the Broken Angel (USA).iso`
4. **Patch file**: `FMA_Undub.xdelta`
5. Click **Apply patch**

```bash
# Or via command line:
xdelta3 -d -s "usa.iso" FMA_Undub.xdelta "FMA_Undub.iso"
```

### Option 2: Full pipeline (with subtitles)

Build from both ISOs. Auto-compiles ffmpeg with subtitle support on first run.

**Requirements**: Python 3.9+, both ISOs, platform build tools

```bash
git clone https://github.com/soyjxck/fma-broken-angel-undub.git
cd fma-broken-angel-undub
pip install -r requirements.txt
python3 patch.py full "path/to/usa.iso" "path/to/jp.iso" "FMA_Undub.iso"
```

**Platform setup** (needed for subtitle burning + MKV export):
- macOS: `brew install libass libx264 pkgconf vgmstream meson`
- Linux: `apt install libass-dev libx264-dev pkg-config build-essential vgmstream meson ninja-build`
- Windows: Use MSYS2 with mingw-w64

**Optional flags:**
- `--dump-mkv <dir>` — Export cutscenes as MKV with JP audio
- `--generate-xdelta` — Also create an xdelta patch file
- `--skip-verify` — Skip ISO hash verification

### Option 3: Audio-only (no subtitles)

Japanese audio only, original English video unchanged. No ffmpeg needed.

```bash
python3 patch.py audio "path/to/usa.iso" "path/to/jp.iso" "FMA_Undub.iso"
```

## Source ISOs

| Version | MD5 |
|---------|-----|
| USA | `e074fae418feff31ee9b4c6422527cab` |
| JP  | `39ee7c7c9773731b9aa6dae943faaec3` |

## How It Works

### Video (DSI Cutscenes)

The game uses Racjin's proprietary **DSI container format** — fixed 0x40000-byte blocks with interleaved MPEG-2 video and PS2 ADPCM audio. Unlike Sony's standard PSS format, DSI has **no timestamps**. A/V sync is entirely determined by the audio/video ratio per block.

We developed a **proportional audio DSI muxer** (the first of its kind — see [dsi-muxer](https://github.com/soyjxck/dsi-muxer)) that distributes audio per block proportional to the number of video frames in that block. This ensures perfect sync regardless of the video encoder used.

### Audio (CDDATA.DIG)

Game audio lives in Racjin's compressed CDDATA.DIG archive — a flat TOC of entries holding voice clips, SFX, music, and SCEI sound banks. We replace each USA entry wholesale with its JP counterpart. When a JP entry is larger than the original USA slot, the archive grows: we append the new entry at end-of-DIG, repoint the TOC sector, and update CDDATA.DIG's ISO9660 directory entry so the file's new sector and size are visible to the game. Result: every JP audio entry replaces its USA counterpart at full original quality, with no resampling.

Earlier versions did per-sample surgery inside SCEI sound banks to preserve USA SFX. That's unnecessary now that the archive can grow — the SFX samples shared between regions are byte-identical, so wholesale-JP banks already contain them in the right positions. See [issue #4](https://github.com/soyjxck/fma-broken-angel-undub/issues/4) for the discussion that led to this simplification.

Compression handled by the [racjin-python](https://github.com/soyjxck/racjin-python) library.

## Fonts

Subtitle dialogue uses **Serifa Std** and title cards use **Geometric Slabserif 703 Extra Bold Condensed**. These fonts are not bundled — subtitle rendering requires them to be installed on the build machine. The xdelta release has subtitles pre-burned into the video, so fonts are only relevant when building from source.

## Credits

- **soyjxck** — Reverse engineering, patch development, tools — [ko-fi](https://ko-fi.com/soyjack)
- **GXZ95** — Hand-translated and timed English subtitles
- **Claude** (Anthropic) — Assisted with reverse engineering and development

## Related Tools

- [dsi-muxer](https://github.com/soyjxck/dsi-muxer) — Racjin PS2 DSI container muxer/demuxer
- [racjin-python](https://github.com/soyjxck/racjin-python) — Racjin compression library

## License

MIT
