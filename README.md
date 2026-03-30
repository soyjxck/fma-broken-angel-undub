# Fullmetal Alchemist and the Broken Angel — Undub Patch

Replaces English audio with Japanese audio in the USA PS2 release. Includes English subtitles on cutscenes.

If this helped you, consider [buying me a coffee](https://ko-fi.com/soyjack) ☕

## What's Changed

| Content | Status |
|---------|--------|
| Cutscene dialogue (18 FMVs) | Japanese audio + English subtitles |
| Opening cutscene | Full JP video + audio |
| In-game voice/SFX | Japanese |
| Combat voice barks | Japanese |
| Music | Japanese |

## How to Patch

### Option 1: xdelta (recommended)

Pre-built patch with Japanese audio **and** English subtitles on all cutscenes. No build tools needed.

**Requirements**: USA ISO + [DeltaPatcher](https://github.com/marco-calautti/DeltaPatcher/releases) (Windows/Mac/Linux)

1. Download `FMA_Undub.xdelta` from [Releases](https://github.com/soyjxck/fma-broken-angel-undub/releases/latest)
2. Open DeltaPatcher
3. **Original file**: `Fullmetal Alchemist and the Broken Angel (USA).iso`
4. **Patch file**: `FMA_Undub.xdelta`
5. Click **Apply patch**

Or via command line:
```bash
xdelta3 -d -s "usa.iso" FMA_Undub.xdelta "FMA_Undub.iso"
```

---

### Option 2: Full pipeline (build it yourself — with subtitles)

Only needed if you want to build the xdelta patch yourself from both ISOs. Produces the same result as Option 1, including burned-in English subtitles. First run will auto-build ffmpeg with subtitle support.

**Requirements**:
- Python 3.9+
- USA ISO + JP ISO
- Platform-specific build tools (see below)

```bash
git clone https://github.com/soyjxck/fma-broken-angel-undub.git
cd fma-broken-angel-undub
python3 patch.py full "path/to/usa.iso" "path/to/jp.iso" "FMA_Undub.iso"
```

#### macOS setup
```bash
# Install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install dependencies (the script auto-installs these, but you can do it manually)
brew install libass libx264 pkgconf
```

#### Linux (Debian/Ubuntu) setup
```bash
sudo apt update
sudo apt install python3 build-essential curl pkg-config \
    libass-dev libx264-dev libfreetype-dev libfribidi-dev \
    libharfbuzz-dev libfontconfig1-dev nasm
```

#### Linux (Fedora/RHEL) setup
```bash
sudo dnf install python3 gcc make curl pkgconf-pkg-config \
    libass-devel x264-devel freetype-devel fribidi-devel \
    harfbuzz-devel fontconfig-devel nasm
```

#### Windows setup
```
1. Install Python 3.9+ from python.org
2. Install MSYS2 from msys2.org
3. In MSYS2 terminal:
   pacman -S mingw-w64-x86_64-gcc mingw-w64-x86_64-libass \
             mingw-w64-x86_64-x264 mingw-w64-x86_64-pkg-config make
4. Run patch.py from MSYS2 terminal
```

The script will automatically download and compile ffmpeg 7.1.1 with libass on first run. Subsequent runs use the cached build.

---

### Option 3: Audio-only (build it yourself — no subtitles)

Same as Option 2 but skips subtitle burning. No ffmpeg or build tools needed — just Python.

**Requirements**: Python 3.9+ + USA ISO + JP ISO

```bash
python3 patch.py audio "path/to/usa.iso" "path/to/jp.iso" "FMA_Undub.iso"
```

---

### Additional flags

| Flag | Description |
|------|-------------|
| `--generate-xdelta` | Also create an xdelta patch file after building the ISO |
| `--skip-verify` | Skip MD5 hash verification of source ISOs |

> **Important**: After patching, use memory card saves in PCSX2 — not save states from the unpatched version.

## Expected MD5 Hashes

| File | MD5 |
|------|-----|
| USA ISO | `e074fae418feff31ee9b4c6422527cab` |
| JP ISO | `39ee7c7c9773731b9aa6dae943faaec3` |

## Known Limitations

- 56 audio entries slightly truncated to fit original ISO slots (barely noticeable)
- Cutscene subtitles are AI-transcribed and manually corrected — minor errors may remain

## Credits

Built with [Claude Code](https://claude.ai/code). See [TECHNICAL.md](TECHNICAL.md) for full reverse engineering documentation.

Tools: [Racjin-de-compression](https://github.com/Raw-man/Racjin-de-compression), [vgmstream](https://github.com/vgmstream/vgmstream), [psxavenc](https://github.com/WonderfulToolchain/psxavenc), [OpenAI Whisper](https://github.com/openai/whisper)

## License

Binary diff patch — requires the original USA ISO. For personal use only.
