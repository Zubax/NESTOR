# Tools

This folder contains standalone self-contained helper scripts for data ingestion, fetching, and server validation.

## `nestor_ingest.py`

Uploads one or more raw `.cf3d` files to the server.
The script reads file bytes, sends them in chunks, retries on transient failures, and prints a final report.

```bash
python tools/nestor_ingest.py --server http://127.0.0.1:8000 --device_uid 0x123 --device "Vehicle-A" data/*.cf3d
```

## `export_cf3d.py`

Dumps CAN frames stored in a Nestor SQLite database to a `.cf3d` file. The
output uses the same record format as live ingest, so it can be replayed with
`nestor_ingest.py`.

```bash
python tools/export_cf3d.py --db nestor.db --device "my device" --out dump.cf3d
```

Pass `--boot-id N` to restrict the export to a single boot session.

## `replay_cf3d.py`

Replays the CAN frames stored in a `.cf3d` file onto a (virtual) CAN interface
via `python-can`. Inter-frame timing is reconstructed from each record's
`hw_ts_us`, so the bus sees traffic at roughly its original rate. CAN FD is
enabled by default to allow payloads larger than 8 bytes.

```bash
python tools/replay_cf3d.py --iface vcan0 dump.cf3d
python tools/replay_cf3d.py --iface vcan0 --speed 2.0 dump.cf3d
python tools/replay_cf3d.py --iface vcan0 --no-timing dump.cf3d
```

Set up `vcan0` first with `sudo modprobe vcan && sudo ip link add dev vcan0 type vcan && sudo ip link set up vcan0`.

## `capture_cf3d.py`

Record live CAN frames from an interface into a `.cf3d` file. Passive listener -- run an allocator (e.g. the DroneCAN GUI Tool) alongside it for plug-and-play nodes.

```bash
python tools/capture_cf3d.py --channel can0 --out gnss.cf3d
```

Bring up `can0` from a Babel first: `sudo slcand -o -c -s8 /dev/ttyACM0 can0 && sudo ip link set up can0`.

## `nestor_replay.py`

Inverse of `nestor_ingest`: pull a device's frames from the server and replay them onto a (virtual) CAN interface. `--follow` for a live tail.

```bash
python tools/nestor_replay.py --server https://cyphalcloud.zubax.com --device "my device" --boot-id 1 --iface vcan0
```

## `e2e_test.py`

Runs a full local E2E check; intended for development only. Read the contents for details.

## `serve_smoke_test.py`

Runs a focused startup smoke test for `nestor serve`:
- launches a real `nestor serve` process in a temporary environment,
- waits for readiness via `GET /cf3d/api/v1/devices`,
- terminates the process and reports detailed diagnostics on failure.

This is the script used by the `nox -s serve_smoke` session.
