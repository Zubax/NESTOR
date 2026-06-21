# Tools

This folder contains standalone self-contained helper scripts for data ingestion, fetching, and server validation.

Each script documents its own invocation examples in its module docstring (run with `--help` or read the top of the file).

| Tool | What it does |
| --- | --- |
| `nestor_ingest.py` | Uploads one or more raw `.cf3d` files to the server. |
| `export_cf3d.py` | Dumps CAN frames from a Nestor SQLite database to a `.cf3d` file. |
| `replay_cf3d.py` | Replays CAN frames from a `.cf3d` file onto a (virtual) CAN interface via `python-can`. Inter-frame timing is reconstructed from each record's `hw_ts_us`. |
| `capture_cf3d.py` | Records live CAN frames from an interface into a `.cf3d` file. |
| `nestor_replay.py` | Inverse of `nestor_ingest`: pulls a device's frames from the server and replays them onto a (virtual) CAN interface. |
| `e2e_test.py` | Runs a full local E2E check; intended for development only. |
| `serve_smoke_test.py` | Focused startup smoke test for `nestor serve` (invoked from Nox): launches a real `nestor serve` process in a temporary environment, waits for readiness via `GET /cf3d/api/v1/devices`, then terminates it and reports diagnostics on failure. |

## Interface setup

Some tools need a (virtual) CAN interface up first:

- **`vcan0`** (for `replay_cf3d.py` / `nestor_replay.py`):
  `sudo modprobe vcan && sudo ip link add dev vcan0 type vcan && sudo ip link set up vcan0`
- **`can0`** from a Zubax Babel (for `capture_cf3d.py`):
  `sudo slcand -o -c -s8 /dev/ttyACM0 can0 && sudo ip link set up can0`
