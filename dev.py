"""Run the local Next.js UI and Python API; stop both when either exits."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    api_port = os.environ.get("API_PORT", "8000")
    ui_port = os.environ.get("PORT", "3000")
    environment = {**os.environ, "INTERVIEWDADDY_API_ORIGIN": f"http://127.0.0.1:{api_port}"}
    api_command = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", api_port]
    if (ROOT / ".env").exists():
        api_command.extend(["--env-file", str(ROOT / ".env")])
    processes: list[subprocess.Popen] = []

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        processes.append(subprocess.Popen(api_command, cwd=ROOT, start_new_session=True))
        processes.append(subprocess.Popen(
            ["npm", "run", "dev", "--", "--hostname", "127.0.0.1", "--port", ui_port],
            cwd=ROOT / "frontend", env=environment, start_new_session=True,
        ))
        print(f"\nInterviewDaddy: http://127.0.0.1:{ui_port}\n", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.2)
        return next((process.returncode for process in processes if process.returncode is not None), 1)
    except KeyboardInterrupt:
        return 0
    finally:
        for process in processes:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
