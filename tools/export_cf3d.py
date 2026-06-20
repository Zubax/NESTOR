#!/usr/bin/env python3
"""
export_cf3d: Dump CAN frames stored in a Nestor SQLite database to a .cf3d file.

The resulting file is byte-identical in format to the .cf3d records the server
ingests via /cf3d/api/v1/commit, so it can be replayed with nestor_ingest.

Usage:
    python tools/export_cf3d.py --db nestor.db --device "my device" --out dump.cf3d
    python tools/export_cf3d.py --db nestor.db --device "my device" --boot-id 0 --out dump.cf3d
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import struct
import sys
from pathlib import Path

from nestor.fec_envelope import box, USER_DATA_BYTES, RECORD_BYTES

LOGGER = logging.getLogger("export_cf3d")


def pack_cf3d_record(boot_id: int, seqno: int, hw_ts_us: int, can_id_with_flags: int, data: bytes) -> bytes:
    if len(data) > 64:
        raise ValueError(f"CAN payload too long: {len(data)} > 64")
    buf = bytearray(USER_DATA_BYTES)
    buf[0] = 0  # version
    struct.pack_into("<QQQ", buf, 8, boot_id, seqno, hw_ts_us)
    struct.pack_into("<I", buf, 36, can_id_with_flags)
    buf[40] = len(data)
    buf[41 : 41 + len(data)] = data
    return box(bytes(buf))


def export(db_path: Path, device: str, boot_id: int | None, out_path: Path) -> int:
    LOGGER.info("Opening database read-only: %s", db_path)
    uri = f"file:{db_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        cursor = connection.cursor()

        cursor.execute("SELECT device_id FROM devices WHERE device=?", (device,))
        row = cursor.fetchone()
        if row is None:
            LOGGER.error("Unknown device %r in %s", device, db_path)
            return 0
        device_id = int(row[0])
        LOGGER.debug("Resolved device=%r to device_id=%d", device, device_id)

        if boot_id is None:
            cursor.execute(
                "SELECT boot_id, seqno, hw_ts_us, can_id_with_flags, data "
                "FROM can_frames WHERE device_id=? ORDER BY seqno ASC",
                (device_id,),
            )
        else:
            cursor.execute(
                "SELECT boot_id, seqno, hw_ts_us, can_id_with_flags, data "
                "FROM can_frames WHERE device_id=? AND boot_id=? ORDER BY seqno ASC",
                (device_id, int(boot_id)),
            )

        written = 0
        with out_path.open("wb") as fh:
            for boot, seqno, hw_ts_us, can_id_with_flags, data in cursor:
                record = pack_cf3d_record(int(boot), int(seqno), int(hw_ts_us), int(can_id_with_flags), bytes(data))
                if len(record) != RECORD_BYTES:
                    LOGGER.critical("pack_cf3d_record produced %d bytes, expected %d", len(record), RECORD_BYTES)
                    raise RuntimeError("internal error: bad record length")
                fh.write(record)
                written += 1
                if written % 1000 == 0:
                    LOGGER.debug("Written %d records so far", written)

        LOGGER.info(
            "Exported %d records (%d bytes) for device=%r boot_id=%s to %s",
            written,
            written * RECORD_BYTES,
            device,
            boot_id if boot_id is not None else "ALL",
            out_path,
        )
        return written
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, required=True, help="Path to nestor.db")
    parser.add_argument("--device", required=True, help="Device name as stored in the database")
    parser.add_argument("--boot-id", type=int, default=None, help="Restrict export to a single boot_id")
    parser.add_argument("--out", type=Path, required=True, help="Output .cf3d file path")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG/INFO/WARNING/ERROR)")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.db.exists():
        LOGGER.error("Database file not found: %s", args.db)
        return 1

    written = export(args.db, args.device, args.boot_id, args.out)
    if written == 0:
        LOGGER.warning("No records exported")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
