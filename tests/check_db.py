import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

import main  # noqa: E402  (importing runs init_db)

print("Database used by the server code:", main.DB_PATH)
main.init_db()
c = sqlite3.connect(main.DB_PATH)
print("Tables:", [r[0] for r in c.execute("select name from sqlite_master where type='table'")])