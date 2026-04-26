import sqlite3
import time

DB_PATH = "/var/lib/nestor/nestor.db"

# Replicate exact server initialization sequence
conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)

# _configure_connection
cursor = conn.cursor()
cursor.execute("PRAGMA foreign_keys=ON")
cursor.execute("PRAGMA busy_timeout=5000")
cursor.execute("PRAGMA temp_store=MEMORY")
cursor.execute("PRAGMA synchronous=NORMAL")
cursor.execute("PRAGMA journal_mode=WAL")
conn.commit()

# _initialize_schema
cursor.executescript("""
    CREATE TABLE IF NOT EXISTS devices
    (
        device_id        INTEGER PRIMARY KEY,
        device           TEXT    NOT NULL UNIQUE,
        last_seqno       INTEGER NOT NULL DEFAULT 0,
        last_heard_ts    INTEGER NOT NULL DEFAULT (CAST(strftime('%s', 'now') AS INTEGER)),
        last_device_uid  INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS can_frames
    (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        commit_ts     INTEGER NOT NULL DEFAULT (CAST(strftime('%s', 'now') AS INTEGER)),
        device_uid    INTEGER NOT NULL,
        device_id     INTEGER NOT NULL,
        hw_ts_us      INTEGER NOT NULL,
        boot_id       INTEGER NOT NULL,
        seqno         INTEGER NOT NULL,
        can_id_with_flags INTEGER NOT NULL,
        data          BLOB    NOT NULL CHECK (length(data) <= 64),
        FOREIGN KEY (device_id) REFERENCES devices(device_id),
        UNIQUE (device_id, seqno)
    );
    CREATE INDEX IF NOT EXISTS can_frames_device_boot_seq
        ON can_frames (device_id, boot_id, seqno);
    CREATE INDEX IF NOT EXISTS can_frames_device_commit
        ON can_frames (device_id, commit_ts);
    CREATE INDEX IF NOT EXISTS can_frames_device_boot_commit
        ON can_frames (device_id, boot_id, commit_ts);
""")
conn.commit()

print("Init done, running query...")

t0 = time.monotonic()
rows = conn.execute(
    "SELECT boot_id, MIN(seqno), MAX(seqno) FROM can_frames WHERE device_id=1 GROUP BY boot_id"
).fetchall()
t1 = time.monotonic()
print(f"Query took {t1-t0:.3f}s, rows={rows}")
conn.close()
