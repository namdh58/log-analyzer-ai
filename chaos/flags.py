"""Toggle flagd feature flags in place by editing demo.flagd.json.

flagd watches its config file and hot-reloads on change, so writing a new
defaultVariant is enough to flip a flag live -- no restart needed.
"""
import json
import os
import signal
import sys
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

FLAGD_CONFIG_PATH = Path(os.environ.get("FLAGD_CONFIG_PATH", "./otel-demo/src/flagd/demo.flagd.json"))


def _load() -> dict:
    return json.loads(FLAGD_CONFIG_PATH.read_text())


def _save(data: dict) -> None:
    FLAGD_CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n")


def set_flag(name: str, variant: str) -> None:
    data = _load()
    if name not in data["flags"]:
        raise KeyError(f"unknown flag: {name}")
    if variant not in data["flags"][name]["variants"]:
        raise KeyError(f"unknown variant {variant!r} for flag {name}")
    data["flags"][name]["defaultVariant"] = variant
    _save(data)


def reset_all() -> None:
    data = _load()
    for flag in data["flags"].values():
        if "off" in flag["variants"]:
            flag["defaultVariant"] = "off"
    _save(data)


def install_signal_handlers() -> None:
    def _reset_and_exit(signum, frame):
        reset_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, _reset_and_exit)
    signal.signal(signal.SIGTERM, _reset_and_exit)


def demo() -> None:
    """ponytail: smallest runnable check -- flip a real flag, verify it round-trips, reset."""
    data = _load()
    original = data["flags"]["paymentFailure"]["defaultVariant"]
    set_flag("paymentFailure", "100%")
    assert _load()["flags"]["paymentFailure"]["defaultVariant"] == "100%"
    reset_all()
    assert _load()["flags"]["paymentFailure"]["defaultVariant"] == "off"
    assert original in ("off", "100%")
    print("chaos.flags: OK")


if __name__ == "__main__":
    demo()
