from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
server = ROOT / "backend" / "server.py"
flags = 0
if os.name == "nt":
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

subprocess.Popen(
    [sys.executable, str(server)],
    cwd=str(ROOT),
    creationflags=flags,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    close_fds=True,
)
port = os.environ.get("YY_DASHBOARD_PORT", "8765")
print(f"Local: http://127.0.0.1:{port}")
try:
    addresses = sorted(
        {
            address
            for address in socket.gethostbyname_ex(socket.gethostname())[2]
            if address and not address.startswith("127.")
        }
    )
except OSError:
    addresses = []
for address in addresses:
    print(f"LAN:   http://{address}:{port}")
