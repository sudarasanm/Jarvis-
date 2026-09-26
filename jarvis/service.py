"""The background service: a small watchdog that keeps Jarvis running.

    pythonw -m jarvis --service

starts Jarvis (`-m jarvis --background`, no console window) and restarts it if it crashes, waiting a little
longer after each crash. After 5 crashes within 10 minutes it gives up (see logs/watchdog.log) rather than
looping forever. When Jarvis exits on purpose ("Jarvis, exit", the tray's Exit, `--stop`) the watchdog exits too.
Runs as you, never as administrator.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from collections import deque

from .state import LOG_DIR, PROJECT_DIR

WATCHDOG_PORT = 47632
WATCHDOG_LOG = LOG_DIR / "watchdog.log"
MAX_CRASHES = 5
CRASH_WINDOW = 600  # seconds
CREATE_NO_WINDOW = 0x08000000


def backoff(crashes: int) -> float:
    """Seconds to wait before restarting after the n-th recent crash: 2, 4, 8, 16... up to a minute."""
    return float(min(60, 2 ** max(crashes, 1)))


class Watchdog:
    def __init__(self, command: list[str] | None = None, spawn=None, clock=time.time):
        self.command = command or [sys.executable, "-m", "jarvis", "--background"]
        self.spawn = spawn or self._spawn
        self.clock = clock
        self.stopping = threading.Event()
        self.crashes: deque[float] = deque()
        self.child = None

    def _spawn(self):
        flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
        return subprocess.Popen(self.command, cwd=str(PROJECT_DIR), creationflags=flags)

    def run(self) -> int:
        """Keep Jarvis running. Returns the number of restarts."""
        restarts = 0
        while not self.stopping.is_set():
            started = self.clock()
            print(f"(starting Jarvis: {' '.join(self.command)})")
            self.child = self.spawn()
            code = self.child.wait()
            if code == 0 or self.stopping.is_set():
                print("(Jarvis exited normally; watchdog stopping)")
                return restarts
            now = self.clock()
            print(f"(Jarvis stopped unexpectedly with code {code} after {now - started:.0f}s)")
            self.crashes.append(now)
            while self.crashes and now - self.crashes[0] > CRASH_WINDOW:
                self.crashes.popleft()
            if len(self.crashes) >= MAX_CRASHES:
                print(f"(Jarvis crashed {len(self.crashes)} times in {CRASH_WINDOW // 60} minutes; giving up. "
                      f"Check {LOG_DIR / 'jarvis.log'}, then start it again.)")
                return restarts
            delay = backoff(len(self.crashes))
            print(f"(restarting in {delay:.0f}s)")
            if self.stopping.wait(delay):
                return restarts
            restarts += 1
        return restarts

    def stop(self) -> None:
        self.stopping.set()


def claim_port() -> socket.socket | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", WATCHDOG_PORT))
    except OSError:
        sock.close()
        return None
    sock.listen(1)
    return sock


def serve_stop(sock: socket.socket, watchdog: Watchdog) -> None:
    def serve():
        while True:
            conn, _ = sock.accept()
            with conn:
                if conn.recv(16).strip() == b"stop":
                    watchdog.stop()
                    conn.sendall(b"ok")

    threading.Thread(target=serve, name="watchdog control", daemon=True).start()


def stop_service() -> bool:
    """Tell a running watchdog not to restart Jarvis (then stop Jarvis itself as usual)."""
    try:
        with socket.create_connection(("127.0.0.1", WATCHDOG_PORT), timeout=3) as conn:
            conn.sendall(b"stop")
            return conn.recv(16) == b"ok"
    except OSError:
        return False


def run_service() -> None:
    from .__main__ import log_to_file

    log_to_file(WATCHDOG_LOG, "Watchdog started")
    lock = claim_port()
    if lock is None:
        print("(the Jarvis service is already running)")
        return
    watchdog = Watchdog()
    serve_stop(lock, watchdog)
    try:
        watchdog.run()
    finally:
        lock.close()
    os._exit(0)
