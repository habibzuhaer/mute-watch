from __future__ import annotations

import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ETHERSCAN_FILE = Path(
    os.getenv("ETHERSCAN_PACE_FILE", str(ROOT / "data" / "etherscan.pace"))
)
_ETHERSCAN_INTERVAL = float(os.getenv("ETHERSCAN_MIN_INTERVAL", "0.4"))


class Pace:
    """In-process spacing between outbound API calls (shared across threads)."""

    def __init__(self, min_interval_sec: float) -> None:
        self.min_interval = max(0.0, float(min_interval_sec))
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            if delay > 0:
                time.sleep(delay)
                now = time.monotonic()
            self._next = now + self.min_interval


class SharedPace:
    """Cross-process spacing via flock — mute + intel + rozvidka share one Etherscan key."""

    def __init__(self, path: Path, min_interval_sec: float) -> None:
        self.path = path
        self.min_interval = max(0.05, float(min_interval_sec))

    def wait(self) -> None:
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.seek(0)
                raw = fh.read().strip()
                last = float(raw) if raw else 0.0
                now = time.time()
                gap = self.min_interval - (now - last)
                if gap > 0:
                    time.sleep(gap)
                    now = time.time()
                fh.seek(0)
                fh.truncate()
                fh.write(f"{now:.6f}")
                fh.flush()
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


_etherscan: SharedPace | None = None
_etherscan_lock = threading.Lock()


def etherscan_wait() -> None:
    global _etherscan
    with _etherscan_lock:
        if _etherscan is None:
            _etherscan = SharedPace(_ETHERSCAN_FILE, _ETHERSCAN_INTERVAL)
        pace = _etherscan
    pace.wait()
