"""Environment management with 1Password injection and hot reload.

Pulse uses op inject to load secrets from .env.op into os.environ.
A background watcher re-injects when the file changes (via Syncthing, etc).

Note: This module uses standard logging, not otel.get_logger(), because
it runs BEFORE OpenTelemetry is initialized.
"""

import logging
import os
import subprocess
import threading
from pathlib import Path

from watchfiles import watch

log = logging.getLogger(__name__)

ENV_OP_FILE = Path("/Pondside/Basement/Env/.env.op")


def inject_env() -> bool:
    """Run op inject and update os.environ with the results.

    Returns True if successful, False otherwise.
    """
    if not ENV_OP_FILE.exists():
        log.warning(f"{ENV_OP_FILE} not found")
        return False

    try:
        result = subprocess.run(
            ["op", "inject", "-i", str(ENV_OP_FILE)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            log.error(f"op inject failed: {result.stderr}")
            return False

        count = 0
        for line in result.stdout.splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                # Strip quotes if present
                value = value.strip().strip('"').strip("'")
                os.environ[key] = value
                count += 1

        log.info(f"Injected {count} environment variables from {ENV_OP_FILE}")
        return True

    except subprocess.TimeoutExpired:
        log.error("op inject timed out")
        return False
    except FileNotFoundError:
        log.error("'op' command not found - is 1Password CLI installed?")
        return False
    except Exception as e:
        log.error(f"Error during op inject: {e}")
        return False


def _watch_env_file():
    """Background thread that watches .env.op for changes."""
    try:
        for changes in watch(ENV_OP_FILE):
            log.info(f"Detected change in {ENV_OP_FILE}, re-injecting...")
            inject_env()
    except Exception as e:
        log.error(f"Env watcher error: {e}")


def start_env_watcher():
    """Start the background file watcher thread."""
    thread = threading.Thread(target=_watch_env_file, daemon=True, name="env-watcher")
    thread.start()
    log.info(f"Watching {ENV_OP_FILE} for changes")
    return thread


def init_env():
    """Initialize environment: inject once, then start watching for changes."""
    inject_env()
    start_env_watcher()
