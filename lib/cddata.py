"""
CDDATA.DIG patching — replaces audio entries with Japanese versions.

CDDATA.DIG is Racjin's archive for all non-cutscene audio (dialogue,
combat voices, SFX, music, menu sounds). Layout is a flat table of
16-byte TOC records at offset 0, followed by sector-aligned entry data
— see DigArchive below.

Per entry, the patcher:
1. Skips byte-identical entries (shared SFX/music between regions)
2. Replaces wholesale with the JP entry — DigArchive grows when JP is
   larger than the original slot, by appending at end-of-DIG and
   repointing the TOC sector. All paths are lossless.

Earlier versions did per-sample SCEI bank surgery (preserving USA SFX
inside mixed banks while replacing voice samples) because the .DIG
couldn't grow, so wholesale replacement of an oversized JP bank meant
truncation. Now that DigArchive grows freely, wholesale JP banks fit
intact — and since SCEI_BANK_MAP was built by hash-matching shared
SFX, those SFX samples are byte-identical between USA and JP banks.
Wholesale-JP therefore preserves them automatically, with no surgery.
"""

import struct

from .constants import SECTOR, SCEI_BANK_MAP, USA_TABLE_OFFSET, JP_TABLE_OFFSET, TABLE_ENTRY_COUNT
from .iso import find_file_in_iso


# =============================================================================
# CDDATA.DIG Archive
# =============================================================================

class DigArchive:
    """Racjin's CDDATA.DIG audio archive — a sector-addressed mini-filesystem.

    Layout: 16-byte TOC entries packed at offset 0, followed by entry data
    at sector-aligned offsets *within this archive* (not within the ISO).
    Each TOC entry is [sector:u32, comp_size:u32, flags:u32, decomp_size:u32].

    Sector arithmetic stays inside this class — callers operate on entry
    indices and bytes.
    """

    def __init__(self, data):
        self.buf = bytearray(data)
        # Next free sector for appended (grown) entries.
        self._next_sector = (len(data) + SECTOR - 1) // SECTOR

    def read_entry(self, idx):
        """Read entry idx. Returns (comp_bytes, decomp_size) or None if empty."""
        toc = idx * 16
        if toc + 16 > len(self.buf):
            return None
        sec, comp_sz, _, decomp_sz = struct.unpack('<IIII', self.buf[toc:toc + 16])
        if sec == 0 or comp_sz == 0:
            return None
        off = sec * SECTOR
        return bytes(self.buf[off:off + comp_sz]), decomp_sz

    def slot_size(self, idx):
        """Original compressed size of entry idx (its in-place capacity)."""
        toc = idx * 16
        return struct.unpack('<I', self.buf[toc + 4:toc + 8])[0]

    def write_entry(self, idx, comp, decomp_size):
        """Replace entry idx. Writes in-place if it fits the original slot,
        otherwise appends at end-of-archive and re-points the TOC sector."""
        toc = idx * 16
        sec, slot = struct.unpack('<II', self.buf[toc:toc + 8])

        if len(comp) <= slot:
            off = sec * SECTOR
            self.buf[off:off + len(comp)] = comp
            self.buf[off + len(comp):off + slot] = b'\x00' * (slot - len(comp))
        else:
            sec = self._next_sector
            new_off = sec * SECTOR
            if new_off > len(self.buf):
                self.buf.extend(b'\x00' * (new_off - len(self.buf)))
            self.buf.extend(comp)
            pad = (SECTOR - (len(comp) % SECTOR)) % SECTOR
            if pad:
                self.buf.extend(b'\x00' * pad)
            self._next_sector = sec + (len(comp) + SECTOR - 1) // SECTOR

        struct.pack_into('<I', self.buf, toc, sec)
        struct.pack_into('<I', self.buf, toc + 4, len(comp))
        struct.pack_into('<I', self.buf, toc + 12, decomp_size)

    def to_bytes(self):
        return bytes(self.buf)


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
    """Patch CDDATA.DIG by replacing USA entries with their JP equivalents.

    For each (usa_entry, jp_entry) pair in the mapping: skip if already
    byte-identical, otherwise wholesale-replace USA's entry with JP's.
    DigArchive grows the archive when the JP entry doesn't fit the
    original USA slot.

    Returns (patched_bytes, replaced_count, skipped_identical, grown_count).
    """
    archive = DigArchive(usa_dig)
    jp_archive = DigArchive(jp_dig)
    replaced = skipped_identical = grown = 0

    for usa_entry, jp_entry in sorted(mapping.items()):
        usa = archive.read_entry(usa_entry)
        jp = jp_archive.read_entry(jp_entry)
        if usa is None or jp is None:
            continue

        usa_comp, _ = usa
        jp_comp, jp_decomp = jp

        if usa_comp == jp_comp:
            skipped_identical += 1
            continue

        if len(jp_comp) > archive.slot_size(usa_entry):
            grown += 1
        archive.write_entry(usa_entry, jp_comp, jp_decomp)
        replaced += 1

    return archive.to_bytes(), replaced, skipped_identical, grown
