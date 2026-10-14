"""Registry: mute / intel / rozvidka stay in their packages; orch only starts/checks them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agents.config import ROOT


@dataclass(frozen=True)
class Module:
    name: str
    role: str
    pid_file: Path
    start_script: Path
    heartbeat_file: Path | None = None


SWARM: dict[str, Module] = {
    "mute": Module(
        name="mute",
        role="collect",
        pid_file=ROOT / "mute.pid",
        start_script=ROOT / "scripts" / "start.sh",
        heartbeat_file=ROOT / "data" / "agents" / "hb_mute.json",
    ),
    "intel": Module(
        name="intel",
        role="relate",
        pid_file=ROOT / "intel.pid",
        start_script=ROOT / "scripts" / "start_intel.sh",
        heartbeat_file=None,
    ),
    "rozvidka": Module(
        name="rozvidka",
        role="speak",
        pid_file=ROOT / "rozvidka.pid",
        start_script=ROOT / "scripts" / "start_rozvidka.sh",
        heartbeat_file=None,
    ),
}

ORDER = ("mute", "intel", "rozvidka")
