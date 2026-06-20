#!/usr/bin/env python3
"""
capture_cf3d: Record live CAN frames from a (v)CAN interface into a .cf3d file.

This is a passive listener: it reads frames from a python-can interface (e.g. a
socketcan `can0` backed by a Zubax Babel via slcand) and writes each one into a
.cf3d file using the exact record layout produced by tools/export_cf3d.py, so
the capture can be replayed unchanged with tools/replay_cf3d.py.

It does NOT allocate node IDs. On a bus with plug-and-play nodes (e.g. a GNSS),
run an allocation server alongside it -- the DroneCAN GUI Tool's dynamic node ID
allocation server is the easy choice -- so the nodes obtain IDs and start
publishing while this tool records. socketcan lets the GUI and this recorder
read the same interface simultaneously.

Usage:
    python tools/capture_cf3d.py --channel can0 --out gnss.cf3d
    python tools/capture_cf3d.py --channel can0 --duration 60 --out gnss.cf3d
    python tools/capture_cf3d.py --channel vcan0 --interface socketcan --out dump.cf3d
"""

from __future__ import annotations

import argparse
import logging
import struct
import sys
import time
from pathlib import Path

import can

from nestor.fec_envelope import box, USER_DATA_BYTES, RECORD_BYTES
from nestor.model import CAN_EFF_FLAG, CAN_RTR_FLAG, CAN_ERR_FLAG, CAN_ID_EXT_MASK

LOGGER = logging.getLogger("capture_cf3d")


def pack_cf3d_record(boot_id: int, seqno: int, hw_ts_us: int, can_id_with_flags: int, data: bytes) -> bytes:
    # Layout copied verbatim from tools/export_cf3d.py so captured records are
    # byte-identical to exported ones and replay is guaranteed.
    if len(data) > 64:
        raise ValueError(f"CAN payload too long: {len(data)} > 64")
    buf = bytearray(USER_DATA_BYTES)
    buf[0] = 0  # version
    struct.pack_into("<QQQ", buf, 8, boot_id, seqno, hw_ts_us)
    struct.pack_into("<I", buf, 36, can_id_with_flags)
    buf[40] = len(data)
    buf[41 : 41 + len(data)] = data
    return box(bytes(buf))


def message_to_can_id_with_flags(msg: can.Message) -> int:
    # Inverse of tools/replay_cf3d.py:to_can_message, so capture -> replay is a
    # faithful round-trip of the arbitration ID and the EFF/RTR/ERR flags.
    value = msg.arbitration_id & CAN_ID_EXT_MASK
    if msg.is_extended_id:
        value |= CAN_EFF_FLAG
    if msg.is_remote_frame:
        value |= CAN_RTR_FLAG
    if msg.is_error_frame:
        value |= CAN_ERR_FLAG
    return value


def capture(channel: str, bustype: str, out_path: Path, boot_id: int, duration: float | None) -> int:
    LOGGER.info("Opening CAN bus interface=%s channel=%s", bustype, channel)
    bus = can.Bus(interface=bustype, channel=channel)
    written = 0
    seqno = 0
    deadline = None if duration is None else time.monotonic() + duration
    LOGGER.info("Recording to %s (boot_id=%d); press Ctrl+C to stop", out_path, boot_id)
    try:
        with out_path.open("wb") as fh:
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    LOGGER.info("Reached requested duration of %.1fs, stopping", duration)
                    break
                msg = bus.recv(timeout=1.0)
                if msg is None:
                    continue

                data = bytes(msg.data)
                if len(data) > 64:
                    LOGGER.warning("Skipping oversized frame: %d bytes", len(data))
                    continue
                hw_ts_us = int(msg.timestamp * 1e6)
                can_id_with_flags = message_to_can_id_with_flags(msg)

                try:
                    record = pack_cf3d_record(boot_id, seqno, hw_ts_us, can_id_with_flags, data)
                except Exception as exc:
                    LOGGER.critical("Failed to pack frame seqno=%d: %s", seqno, exc, exc_info=True)
                    continue
                if len(record) != RECORD_BYTES:
                    LOGGER.critical("pack_cf3d_record produced %d bytes, expected %d", len(record), RECORD_BYTES)
                    continue

                fh.write(record)
                LOGGER.debug(
                    "recorded seqno=%d can_id=0x%08x dlc=%d hw_ts_us=%d",
                    seqno,
                    can_id_with_flags,
                    len(data),
                    hw_ts_us,
                )
                seqno += 1
                written += 1
                if written % 1000 == 0:
                    LOGGER.debug("Recorded %d frames so far", written)
    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user, stopping")
    finally:
        LOGGER.info("Shutting down CAN bus")
        bus.shutdown()

    LOGGER.info("Capture finished: recorded %d frames (%d bytes) to %s", written, written * RECORD_BYTES, out_path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="Output .cf3d file path")
    parser.add_argument("--channel", default="can0", help="CAN interface channel (default: can0)")
    parser.add_argument("--interface", default="socketcan", help="python-can interface name (default: socketcan)")
    parser.add_argument(
        "--boot-id",
        type=int,
        default=None,
        help="Boot ID stamped into every record (default: current Unix time)",
    )
    parser.add_argument("--duration", type=float, default=None, help="Stop automatically after N seconds")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG/INFO/WARNING/ERROR)")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.duration is not None and args.duration <= 0:
        LOGGER.error("--duration must be positive, got %r", args.duration)
        return 1

    boot_id = args.boot_id if args.boot_id is not None else int(time.time())

    try:
        written = capture(
            channel=args.channel,
            bustype=args.interface,
            out_path=args.out,
            boot_id=boot_id,
            duration=args.duration,
        )
    except Exception as exc:
        LOGGER.critical("Capture failed: %s", exc, exc_info=True)
        return 1

    if written == 0:
        LOGGER.warning("No frames recorded")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
