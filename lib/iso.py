"""
ISO9660 filesystem helpers.

Provides functions to locate files within a PS2 ISO image and verify
ISO integrity via MD5 hash checking.
"""

import struct
import os
import hashlib

from .constants import SECTOR_SIZE


def find_file_in_iso(iso_data, filename):
    """Find a file's sector, size, and directory entry offset in an ISO.

    Searches for the filename in the ISO9660 directory entries and returns
    the file's starting sector, size in bytes, and the byte offset of the
    directory entry (useful for patching the entry later).

    Args:
        iso_data: Raw bytes of the entire ISO image.
        filename: Filename to find (bytes or str). Use ISO format like b'M004.DSI;1'.

    Returns:
        Tuple of (sector, size, dir_entry_offset) or None if not found.
    """
    search = filename.encode() if isinstance(filename, str) else filename
    pos = iso_data.find(search)
    if pos < 0:
        return None
    entry = pos - 33
    sector = struct.unpack('<I', iso_data[entry + 2:entry + 6])[0]
    size = struct.unpack('<I', iso_data[entry + 10:entry + 14])[0]
    return sector, size, entry


def update_dir_entry(f, entry_offset, sector, size):
    """Update an ISO9660 directory entry's sector and size (both LE and BE).

    Args:
        f: File object opened in r+b mode.
        entry_offset: Byte offset of the directory entry in the ISO.
        sector: New starting sector.
        size: New file size in bytes.
    """
    f.seek(entry_offset + 2)
    f.write(struct.pack('<I', sector))
    f.write(struct.pack('>I', sector))
    f.seek(entry_offset + 10)
    f.write(struct.pack('<I', size))
    f.write(struct.pack('>I', size))


def verify_iso(path, label, expected, skip=False):
    """Verify an ISO file's size and MD5 hash.

    Args:
        path: Path to the ISO file.
        label: Display label (e.g., 'USA', 'JP').
        expected: Dict with 'size' and 'md5' keys.
        skip: If True, skip MD5 verification (size check only).

    Returns:
        True if verification passed (or was skipped).
    """
    size = os.path.getsize(path)
    if size != expected['size']:
        print(f"  WARNING: {label} size mismatch ({size:,} vs {expected['size']:,})")

    if skip:
        return True

    print(f"  Verifying {label}...", end=' ', flush=True)
    with open(path, 'rb') as f:
        md5 = hashlib.md5(f.read()).hexdigest()
    if md5 == expected['md5']:
        print("OK")
        return True
    else:
        print(f"MISMATCH (got {md5})")
        print(f"  Your ISO may be a different dump. Proceeding anyway...")
        return False
