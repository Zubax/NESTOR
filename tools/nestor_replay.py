#!/usr/bin/env python3
"""
nestor_replay: Replay CAN frames stored on a Nestor server onto a (v)CAN interface.

The inverse of nestor_ingest: instead of pushing .cf3d records to the server, this
pulls a device's recorded frames back out via the REST query API
(GET /cf3d/api/v1/records) and transmits them with python-can, so any DroneCAN tool
(e.g. the DroneCAN GUI Tool) can decode/plot an archived session as if it were live.

Records are paged by seqno (server caps each page; default/max page size 10000) and
replayed with inter-frame delays derived from hw_ts_us, preserving original timing.
With --follow it long-polls for new records and keeps streaming (live tail).

Usage:
    python tools/nestor_replay.py --server https://cyphalcloud.zubax.com \
        --device "gnss-bench-test" --boot-id 1781871628 --iface vcan0
    python tools/nestor_replay.py --server http://localhost:8000 \
        --device my-drone --boot-id 1 --iface vcan0 --speed 2.0
    python tools/nestor_replay.py --server http://localhost:8000 \
        --device my-drone --boot-id 1 --iface vcan0 --follow

Set up vcan0 first with `sudo modprobe vcan && sudo ip link add dev vcan0 type vcan && sudo ip link set up vcan0`.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import can

LOGGER = logging.getLogger("nestor_replay")

RECORDS_PATH = "/cf3d/api/v1/records"
MAX_PAGE_LIMIT = 10000
REQUEST_TIMEOUT_S = 60.0
# Server-side long-poll cap (see rest_api.WAIT_MAX_TIMEOUT_S).
FOLLOW_WAIT_TIMEOUT_S = 30


def fetch_page(
    server: str,
    device: str,
    boot_ids: list[int],
    seqno_min: int | None,
    limit: int,
    wait_timeout_s: int,
) -> dict:
    base = server.rstrip("/") + RECORDS_PATH
    query: list[tuple[str, str]] = [("device", device)]
    for boot_id in boot_ids:
        query.append(("boot_id", str(boot_id)))
    if seqno_min is not None:
        query.append(("seqno_min", str(seqno_min)))
    query.append(("limit", str(limit)))
    if wait_timeout_s > 0:
        query.append(("wait_timeout_s", str(wait_timeout_s)))
    url = base + "?" + urllib.parse.urlencode(query)
    LOGGER.debug("GET %s", url)
    request = urllib.request.Request(url=url, method="GET")
    request.add_header("Accept", "application/json")
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
        body = response.read()
    return json.loads(body)


def record_to_can_message(record: dict) -> tuple[int, can.Message]:
    # The records DTO pre-splits the flags, so no can_id_with_flags math is needed.
    frame = record["frame"]
    data = bytes.fromhex(frame["data_hex"])
    msg = can.Message(
        arbitration_id=int(frame["can_id"]),
        is_extended_id=bool(frame["extended"]),
        is_remote_frame=bool(frame["rtr"]),
        is_error_frame=bool(frame["error"]),
        is_fd=len(data) > 8,
        data=data,
    )
    return int(record["hw_ts_us"]), msg


def replay(
    server: str,
    device: str,
    boot_ids: list[int],
    iface: str,
    bustype: str,
    speed: float,
    respect_timing: bool,
    follow: bool,
    fd: bool,
    dry_run: bool,
) -> int:
    if dry_run:
        LOGGER.info("Dry run: fetching from %s without opening a CAN bus", server)
        bus = None
    else:
        LOGGER.info("Opening CAN bus interface=%s bustype=%s fd=%s", iface, bustype, fd)
        bus = can.Bus(interface=bustype, channel=iface, fd=fd)

    sent = 0
    seqno_min: int | None = None
    first_hw_ts_us: int | None = None
    wall_start: float | None = None
    try:
        while True:
            wait = FOLLOW_WAIT_TIMEOUT_S if follow else 0
            try:
                page = fetch_page(server, device, boot_ids, seqno_min, MAX_PAGE_LIMIT, wait)
            except urllib.error.HTTPError as exc:
                LOGGER.critical("Server returned HTTP %d: %s", exc.code, exc.read().decode("utf-8", "replace"))
                return sent
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                LOGGER.critical("Failed to reach server %s: %s", server, exc)
                return sent

            records = page.get("records", [])
            if not records:
                if follow:
                    LOGGER.debug("No new records; long-polling again")
                    continue
                LOGGER.info("No more records")
                break

            LOGGER.debug("Fetched %d records (seqno_min=%s)", len(records), seqno_min)
            for record in records:
                try:
                    hw_ts_us, msg = record_to_can_message(record)
                except Exception as exc:
                    LOGGER.critical("Failed to build frame for seqno=%s: %s", record.get("seqno"), exc)
                    continue

                if respect_timing and not dry_run:
                    if first_hw_ts_us is None:
                        first_hw_ts_us = hw_ts_us
                        wall_start = time.monotonic()
                    else:
                        target = wall_start + (hw_ts_us - first_hw_ts_us) / 1e6 / speed
                        delay = target - time.monotonic()
                        if delay > 0:
                            time.sleep(delay)

                if dry_run:
                    LOGGER.debug("dry-run would send: %s", msg)
                else:
                    try:
                        bus.send(msg)
                    except can.CanError as exc:
                        LOGGER.critical("bus.send failed for seqno=%s: %s", record.get("seqno"), exc)
                        continue
                sent += 1
                if sent % 1000 == 0:
                    LOGGER.debug("Sent %d frames so far", sent)

            # Page by seqno: resume after the last record returned (lossless pagination).
            seqno_min = int(records[-1]["seqno"]) + 1
    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user, stopping")
    finally:
        if bus is not None:
            LOGGER.info("Shutting down CAN bus")
            bus.shutdown()

    LOGGER.info("Replay finished: sent=%d from server=%s device=%r", sent, server, device)
    return sent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", required=True, help="Base server URL, e.g. https://cyphalcloud.zubax.com")
    parser.add_argument("--device", required=True, help="Device name as stored on the server")
    parser.add_argument(
        "--boot-id",
        type=int,
        action="append",
        required=True,
        help="Boot ID to replay (repeat for multiple; timing is anchored on the first frame seen)",
    )
    parser.add_argument("--iface", default="vcan0", help="CAN interface channel (default: vcan0)")
    parser.add_argument("--bustype", default="socketcan", help="python-can interface name (default: socketcan)")
    parser.add_argument("--speed", type=float, default=1.0, help="Replay speed multiplier (default: 1.0)")
    parser.add_argument("--no-timing", action="store_true", help="Send as fast as possible, ignore hw_ts_us")
    parser.add_argument("--follow", action="store_true", help="Keep long-polling for new records (live tail)")
    parser.add_argument("--no-fd", action="store_true", help="Disable CAN FD on the bus")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and log frames without opening a bus")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG/INFO/WARNING/ERROR)")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parsed = urllib.parse.urlsplit(args.server)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        LOGGER.error("--server must be a valid absolute http(s) URL, got %r", args.server)
        return 1
    if args.speed <= 0:
        LOGGER.error("--speed must be positive, got %r", args.speed)
        return 1
    if len(args.boot_id) > 1 and not args.no_timing:
        LOGGER.warning(
            "Replaying %d boots with timing: hw_ts_us resets per boot, so timing may jump at boot boundaries",
            len(args.boot_id),
        )

    sent = replay(
        server=args.server,
        device=args.device,
        boot_ids=sorted(set(args.boot_id)),
        iface=args.iface,
        bustype=args.bustype,
        speed=args.speed,
        respect_timing=not args.no_timing,
        follow=args.follow,
        fd=not args.no_fd,
        dry_run=args.dry_run,
    )
    if sent == 0:
        LOGGER.warning("No frames replayed")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
