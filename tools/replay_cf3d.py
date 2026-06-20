#!/usr/bin/env python3
"""
replay_cf3d: Replay CAN frames from a .cf3d file onto a (v)CAN interface.

Reads RECORD_BYTES-sized records, unboxes them with the FEC envelope, decodes
the same user-data layout produced by tools/export_cf3d.py, and transmits the
frames via python-can. Inter-frame delays are derived from hw_ts_us so the
replay preserves the original timing.

Usage:
    python tools/replay_cf3d.py --iface vcan0 dump.cf3d
    python tools/replay_cf3d.py --iface vcan0 --speed 2.0 dump.cf3d
    python tools/replay_cf3d.py --iface vcan0 --no-timing dump.cf3d
"""

from __future__ import annotations

import argparse
import logging
import struct
import sys
import time
from pathlib import Path

import can

from nestor.fec_envelope import unbox, UnboxError, RECORD_BYTES
from nestor.model import CAN_EFF_FLAG, CAN_RTR_FLAG, CAN_ERR_FLAG, CAN_ID_EXT_MASK

LOGGER = logging.getLogger("replay_cf3d")


def unpack_cf3d_record(user: bytes) -> tuple[int, int, int, int, bytes]:
    version = user[0]
    if version != 0:
        raise ValueError(f"unsupported cf3d record version: {version}")
    boot_id, seqno, hw_ts_us = struct.unpack_from("<QQQ", user, 8)
    (can_id_with_flags,) = struct.unpack_from("<I", user, 36)
    dlc = user[40]
    if dlc > 64:
        raise ValueError(f"invalid CAN payload length: {dlc}")
    data = bytes(user[41 : 41 + dlc])
    return boot_id, seqno, hw_ts_us, can_id_with_flags, data


def to_can_message(can_id_with_flags: int, data: bytes) -> can.Message:
    return can.Message(
        arbitration_id=can_id_with_flags & CAN_ID_EXT_MASK,
        is_extended_id=bool(can_id_with_flags & CAN_EFF_FLAG),
        is_remote_frame=bool(can_id_with_flags & CAN_RTR_FLAG),
        is_error_frame=bool(can_id_with_flags & CAN_ERR_FLAG),
        is_fd=len(data) > 8,
        data=data,
    )


def replay(
    path: Path,
    iface: str,
    bustype: str,
    speed: float,
    respect_timing: bool,
    fd: bool,
    dry_run: bool,
) -> int:
    if dry_run:
        LOGGER.info("Dry run: parsing %s without opening a CAN bus", path)
        bus = None
    else:
        LOGGER.info("Opening CAN bus interface=%s bustype=%s fd=%s", iface, bustype, fd)
        bus = can.Bus(interface=bustype, channel=iface, fd=fd)
    sent = 0
    skipped = 0
    first_hw_ts_us: int | None = None
    wall_start: float | None = None
    try:
        with path.open("rb") as fh:
            LOGGER.info("Reading cf3d records from %s", path)
            while True:
                record = fh.read(RECORD_BYTES)
                if not record:
                    break
                if len(record) != RECORD_BYTES:
                    LOGGER.warning("Trailing %d bytes ignored (not a full record)", len(record))
                    break

                result = unbox(record)
                if isinstance(result, UnboxError):
                    LOGGER.warning("Skipping unboxable record #%d: %s", sent + skipped, result)
                    skipped += 1
                    continue
                user = result

                try:
                    boot_id, seqno, hw_ts_us, can_id_with_flags, data = unpack_cf3d_record(user)
                except Exception as exc:
                    LOGGER.critical("Failed to unpack record #%d: %s", sent + skipped, exc)
                    skipped += 1
                    continue

                LOGGER.debug(
                    "record boot_id=%d seqno=%d hw_ts_us=%d can_id=0x%08x dlc=%d",
                    boot_id,
                    seqno,
                    hw_ts_us,
                    can_id_with_flags,
                    len(data),
                )

                if respect_timing and not dry_run:
                    if first_hw_ts_us is None:
                        first_hw_ts_us = hw_ts_us
                        wall_start = time.monotonic()
                    else:
                        target = wall_start + (hw_ts_us - first_hw_ts_us) / 1e6 / speed
                        delay = target - time.monotonic()
                        if delay > 0:
                            time.sleep(delay)

                msg = to_can_message(can_id_with_flags, data)
                if dry_run:
                    LOGGER.debug("dry-run would send: %s", msg)
                else:
                    try:
                        bus.send(msg)
                    except can.CanError as exc:
                        LOGGER.critical("bus.send failed for seqno=%d: %s", seqno, exc)
                        skipped += 1
                        continue
                sent += 1
                if sent % 1000 == 0:
                    LOGGER.debug("Sent %d frames so far", sent)
    finally:
        if bus is not None:
            LOGGER.info("Shutting down CAN bus")
            bus.shutdown()

    LOGGER.info("Replay finished: sent=%d skipped=%d from %s", sent, skipped, path)
    return sent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path, help="Path to .cf3d file to replay")
    parser.add_argument("--iface", default="vcan0", help="CAN interface channel (default: vcan0)")
    parser.add_argument("--bustype", default="socketcan", help="python-can interface name (default: socketcan)")
    parser.add_argument("--speed", type=float, default=1.0, help="Replay speed multiplier (default: 1.0)")
    parser.add_argument("--no-timing", action="store_true", help="Send as fast as possible, ignore hw_ts_us")
    parser.add_argument("--no-fd", action="store_true", help="Disable CAN FD on the bus")
    parser.add_argument("--dry-run", action="store_true", help="Parse file and log frames without opening a bus")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG/INFO/WARNING/ERROR)")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.file.exists():
        LOGGER.error("Input file not found: %s", args.file)
        return 1
    if args.speed <= 0:
        LOGGER.error("--speed must be positive, got %r", args.speed)
        return 1

    sent = replay(
        path=args.file,
        iface=args.iface,
        bustype=args.bustype,
        speed=args.speed,
        respect_timing=not args.no_timing,
        fd=not args.no_fd,
        dry_run=args.dry_run,
    )
    if sent == 0:
        LOGGER.warning("No frames replayed")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
