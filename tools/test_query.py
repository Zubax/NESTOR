import sqlite3
import time

conn = sqlite3.connect("/var/lib/nestor/nestor.db")
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
t0 = time.monotonic()
rows = conn.execute(
    "SELECT boot_id, MIN(seqno), MAX(seqno) FROM can_frames WHERE device_id=1 GROUP BY boot_id"
).fetchall()
t1 = time.monotonic()
print(f"Query took {t1-t0:.3f}s, rows={rows}")
conn.close()
