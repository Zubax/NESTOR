# Tools

This folder contains standalone self-contained helper scripts for data ingestion, fetching, and server validation.

Each script documents its own invocation examples in its module docstring (run with `--help` or read the top of the file).

| Tool | What it does |
| --- | --- |
| `nestor_ingest.py` | Uploads one or more raw `.cf3d` files to the server. Reads file bytes, sends them in chunks, retries on transient failures, and prints a final report. |
| `export_cf3d.py` | Dumps CAN frames from a Nestor SQLite database to a `.cf3d` file. Output uses the same record format as live ingest, so it can be replayed with `nestor_ingest.py`. Pass `--boot-id N` to restrict to a single boot session. |
| `replay_cf3d.py` | Replays CAN frames from a `.cf3d` file onto a (virtual) CAN interface via `python-can`. Inter-frame timing is reconstructed from each record's `hw_ts_us`. CAN FD is enabled by default to allow payloads larger than 8 bytes. |
| `capture_cf3d.py` | Records live CAN frames from an interface into a `.cf3d` file. Passive listener -- run an allocator (e.g. the DroneCAN GUI Tool) alongside it for plug-and-play nodes. |
| `nestor_replay.py` | Inverse of `nestor_ingest`: pulls a device's frames from the server and replays them onto a (virtual) CAN interface. `--follow` for a live tail. |
| `e2e_test.py` | Runs a full local E2E check; intended for development only. Read the contents for details. |
| `serve_smoke_test.py` | Focused startup smoke test for `nestor serve` (used by the `nox -s serve_smoke` session): launches a real `nestor serve` process in a temporary environment, waits for readiness via `GET /cf3d/api/v1/devices`, then terminates it and reports diagnostics on failure. |

## Interface setup

Some tools need a (virtual) CAN interface up first:

- **`vcan0`** (for `replay_cf3d.py` / `nestor_replay.py`):
  `sudo modprobe vcan && sudo ip link add dev vcan0 type vcan && sudo ip link set up vcan0`
- **`can0`** from a Zubax Babel (for `capture_cf3d.py`):
  `sudo slcand -o -c -s8 /dev/ttyACM0 can0 && sudo ip link set up can0`
