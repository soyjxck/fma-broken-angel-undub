# Fullmetal Alchemist and the Broken Angel — Undub Patch

Replaces English audio with Japanese audio in the USA PS2 release. Includes English subtitles on cutscenes.

If this helped you, consider [buying me a coffee](https://ko-fi.com/soyjack)

## What's Changed

| Content | Status |
|---------|--------|
| Cutscene dialogue (18 FMVs) | Japanese audio + English subtitles |
| Opening cutscene | Full JP video + audio + subtitles |
| In-game voice/SFX | Japanese (per-sample replacement) |
| Combat voice barks | Japanese |
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
pip install -r requirements.txt  # or: uv pip install racjin dsi-muxer
python3 patch.py full "path/to/usa.iso" "path/to/jp.iso" "FMA_Undub.iso"
```

**Platform setup:**
- macOS: `brew install libass libx264 pkgconf vgmstream`
- Linux: `apt install libass-dev libx264-dev pkg-config build-essential`
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

Game audio lives in Racjin's compressed CDDATA.DIG archive. We use **per-sample SCEI sound bank replacement**: individual voice samples within banks are replaced with JP equivalents while keeping shared SFX (menu sounds, combat effects) untouched. This preserves all game functionality while changing only the voice content.

Compression handled by the [racjin-python](https://github.com/soyjxck/racjin-python) library.

## Known Limitations

- ~49 in-game dialogue entries stay in English (JP version is larger than available slot)
- Cutscene video quality is slightly lower than original (re-encoded at ~90-95% bitrate to accommodate proportional audio)
- Last ~0.5s of some cutscenes may have fewer video frames than the original

## Credits

- **soyjxck** — Reverse engineering, patch development, tools
- **GXZ95** — Updated translation subtitles
- **Claude** (Anthropic) — Assisted with reverse engineering and development

## Related Tools

- [dsi-muxer](https://github.com/soyjxck/dsi-muxer) — Racjin PS2 DSI container muxer/demuxer
- [racjin-python](https://github.com/soyjxck/racjin-python) — Racjin compression library

## License

MIT
