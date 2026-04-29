"""
ISO9660 filesystem helpers.

The ISO is treated as a flat array of 2048-byte sectors. Files are located
by directory entry, read by slicing the ISO bytes, and written by seeking
to a sector and updating the directory entry. All sector arithmetic is
contained in this module — callers operate on file names and byte buffers.
"""

import struct
import os
import hashlib

from .constants import SECTOR


def find_file_in_iso(iso_data, filename):
    """Find a file's sector, size, and directory entry offset in an ISO.

    The search is a raw byte scan for the ISO9660-encoded filename
    (e.g. b'M025.DSI;1'). It assumes the filename only appears inside its
    directory record — generally safe for uppercase-ASCII names with the
    `;1` revision suffix, which don't show up in audio/video payloads.

    Returns:
        Tuple of (sector, size, dir_entry_offset) or None if not found.
    """
    search = filename.encode() if isinstance(filename, str) else filename
    pos = iso_data.find(search)
    if pos < 0:
        return None
    # ISO9660 directory record layout: name lives at offset 33; sector
    # extent (LE+BE u32) at offset 2; size (LE+BE u32) at offset 10.
    entry = pos - 33
    sector = struct.unpack('<I', iso_data[entry + 2:entry + 6])[0]
    size = struct.unpack('<I', iso_data[entry + 10:entry + 14])[0]
    return sector, size, entry


def read_file_from_iso(iso_data, filename):
    """Locate and slice a file's bytes out of the ISO.

    Returns:
        Tuple of (data, dir_entry_offset) or None if not found. The dir
        offset is returned so callers can later relocate/resize the file.
    """
    info = find_file_in_iso(iso_data, filename)
    if info is None:
        return None
    sector, size, dir_offset = info
    return iso_data[sector * SECTOR:sector * SECTOR + size], dir_offset


def write_file_to_iso(f, dir_offset, sector, data):
    """Write a file at the given sector, pad to sector boundary, and update
    its directory entry to match the new sector and size.

    Args:
        f: File object opened in r+b mode.
        dir_offset: Byte offset of the file's directory entry in the ISO.
        sector: Sector at which to write the file's contents.
        data: File contents.

    Returns:
        The next free sector after this file (sector + ceil(len(data)/SECTOR)).
    """
    f.seek(sector * SECTOR)
    f.write(data)
    pad = (SECTOR - (len(data) % SECTOR)) % SECTOR
    if pad:
        f.write(b'\x00' * pad)
    update_dir_entry(f, dir_offset, sector, len(data))
    return sector + (len(data) + SECTOR - 1) // SECTOR


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
    md5_hash = hashlib.md5()
    with open(path, 'rb') as f:
        while chunk := f.read(64 * 1024 * 1024):
            md5_hash.update(chunk)
    md5 = md5_hash.hexdigest()
    if md5 == expected['md5']:
        print("OK")
        return True
    else:
        print(f"MISMATCH (got {md5})")
        print(f"  Your ISO may be a different dump. Proceeding anyway...")
        return False
