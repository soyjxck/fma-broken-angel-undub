"""
Constants, lookup tables, and expected hashes for the FMA Undub Patcher.
"""

# =============================================================================
# DSI Container
# =============================================================================

DSI_BLOCK_SIZE = 0x40000     # 262,144 bytes per block
AUDIO_TYPE_TAG = -8192       # 0xFFFFE000 — identifies audio stream in block header
VIDEO_TYPE_TAG = -16384      # 0xFFFFC000 — identifies video stream in block header

# =============================================================================
# ISO / CDDATA
# =============================================================================

SECTOR = 2048           # ISO9660 sector size

# Offsets into game executables where the CDDATA entry lookup tables live
USA_TABLE_OFFSET = 0x1B612E  # in SLUS_209.94
JP_TABLE_OFFSET = 0x1B52EE   # in SLPM_654.73
TABLE_ENTRY_COUNT = 101      # entries in each lookup table

# =============================================================================
# Expected ISO hashes for verification
# =============================================================================

EXPECTED_HASHES = {
    'usa': {'size': 1927217152, 'md5': 'e074fae418feff31ee9b4c6422527cab'},
    'jp':  {'size': 1732345856, 'md5': '39ee7c7c9773731b9aa6dae943faaec3'},
}

# =============================================================================
# SCEI Sound Bank Mapping
# =============================================================================
# Maps USA CDDATA entry indices to JP entry indices for SCEI sound banks.
# These contain combat voice clips, character grunts, and some SFX.
# Built from MD5 hash matching of individual ADPCM samples + voice bank
# count matching across USA and JP versions.

SCEI_BANK_MAP = {
    # Matched by sample hash (shared SFX identify the bank, different samples are voice)
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
    # Matched by voice bank count (zero shared samples)
    # 105/107/108 are identical USA banks (3 voice samples). JP 263 has 1 SFX + 3 voice,
    # so JP sample indices are offset by 1 (USA[i] → JP[i+1]).
    105:263, 107:263, 108:263,
    141:245, 142:462, 143:247, 146:334,
    151:462, 152:463, 153:464, 156:467, 157:468,
}

# =============================================================================
# DSI Cutscene Names
# =============================================================================
# All 18 cutscene DSI files in the game.
# M000 = opening (uses full JP DSI replacement, different video+audio)
# M001, M003 = no dialogue (audio-only, no subtitles)

DSI_NAMES = [
    'M000', 'M001', 'M002', 'M003', 'M004', 'M005', 'M006', 'M008',
    'M010', 'M014', 'M015', 'M016', 'M018', 'M021', 'M022', 'M023',
    'M024', 'M025',
]

# Subtitle files are in the subs/ directory alongside the main script
import os
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBS_DIR = os.path.join(SCRIPT_DIR, 'subs')
