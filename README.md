# Fullmetal Alchemist and the Broken Angel — Undub Patch

Replaces English audio with Japanese audio in the USA PS2 release. Includes English subtitles on cutscenes.

**[Download latest patch](https://github.com/soyjxck/fma-broken-angel-undub/releases/latest)**

## What's Changed

| Content | Status |
|---------|--------|
| Cutscene dialogue (18 FMVs) | Japanese audio + English subtitles |
| Opening cutscene | Full JP video + audio |
| In-game voice/SFX | Japanese |
| Combat voice barks | Japanese |
| Music | Japanese |

## How to Apply

1. Download `FMA_Undub.xdelta` from [Releases](https://github.com/soyjxck/fma-broken-angel-undub/releases/latest)
2. Download [DeltaPatcher](https://github.com/marco-calautti/DeltaPatcher/releases) (GUI, any platform)
3. **Original file**: Your USA ISO (`Fullmetal Alchemist and the Broken Angel (USA).iso`)
4. **Patch file**: `FMA_Undub.xdelta`
5. Click **Apply patch**
6. Play in PCSX2

> **Note**: Use memory card saves, not save states from the unpatched version.

## Known Limitations

- 56 audio entries slightly truncated to fit (barely noticeable)
- Cutscene subtitles are AI-transcribed and manually corrected — minor errors may remain

## Credits

Built with [Claude Code](https://claude.ai/code). See [TECHNICAL.md](TECHNICAL.md) for full reverse engineering documentation.

Tools: [Racjin-de-compression](https://github.com/Raw-man/Racjin-de-compression), [vgmstream](https://github.com/vgmstream/vgmstream), [psxavenc](https://github.com/WonderfulToolchain/psxavenc), [OpenAI Whisper](https://github.com/openai/whisper)

## License

Binary diff patch — requires the original USA ISO. For personal use only.
