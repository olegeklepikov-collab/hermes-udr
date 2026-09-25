"""Bound local parser processes and their children; this is resource isolation, not a security sandbox."""

import argparse
import math
import os
import signal
import subprocess
import sys
import tempfile
import time


def run_bounded(
    command,
    *,
    wall_seconds=120,
    memory_bytes=1_500_000_000,
    output_bytes=30_000_000,
    cwd=None,
):
    if (
        type(wall_seconds) not in (float, int)
        or not math.isfinite(wall_seconds)
        or not 0 < wall_seconds <= 14400
        or type(memory_bytes) is not int
        or not 16_000_000 <= memory_bytes <= 32_000_000_000
        or type(output_bytes) is not int
        or not 1 <= output_bytes <= 100_000_000
    ):
        raise ValueError("parser_resource_limits_invalid")
    try:
        import psutil
    except ImportError:
        raise ValueError("parser_resource_monitor_missing") from None
    start = time.monotonic()
    peak = 0
    descendants = []
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            command, cwd=cwd, stdout=stdout, stderr=stderr, start_new_session=True
        )
        parent = psutil.Process(process.pid)
        try:
            while True:
                try:
                    descendants = parent.children(recursive=True)
                    rss = sum(
                        p.memory_info().rss
                        for p in [parent, *descendants]
                        if p.is_running()
                    )
                except psutil.NoSuchProcess:
                    rss = 0
                peak = max(peak, rss)
                if peak > memory_bytes:
                    raise ValueError("parser_memory_limit_exceeded")
                if (
                    os.fstat(stdout.fileno()).st_size
                    + os.fstat(stderr.fileno()).st_size
                    > output_bytes
                ):
                    raise ValueError("parser_output_limit_exceeded")
                if time.monotonic() - start > wall_seconds:
                    raise ValueError("parser_wall_limit_exceeded")
                if process.poll() is not None:
                    break
                time.sleep(0.02)
            stdout.seek(0)
            stderr.seek(0)
            return {
                "returncode": process.returncode,
                "stdout": stdout.read(output_bytes + 1),
                "stderr": stderr.read(output_bytes + 1),
                "peak_rss_bytes": peak,
                "wall_seconds": time.monotonic() - start,
            }
        finally:
            # Also terminate children left behind by a completed parser.
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                for child in descendants:
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                if process.poll() is None:
                    process.kill()
            process.wait(timeout=5)


def guarded_main(main):
    """Protect parser CLI entry points; direct unit-tested functions remain callable."""
    if sys.argv[1:2] == ["--bounded-parser-worker"]:
        return main(sys.argv[2:])
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--parser-wall-seconds", type=float, default=180)
    parser.add_argument("--parser-memory-bytes", type=int, default=1_500_000_000)
    limits, args = parser.parse_known_args()
    try:
        result = run_bounded(
            [
                sys.executable,
                str(os.path.abspath(sys.argv[0])),
                "--bounded-parser-worker",
                *args,
            ],
            wall_seconds=limits.parser_wall_seconds,
            memory_bytes=limits.parser_memory_bytes,
        )
        sys.stdout.buffer.write(result["stdout"])
        sys.stderr.buffer.write(result["stderr"])
        return result["returncode"] if result["returncode"] >= 0 else 2
    except (ValueError, OSError) as error:
        import json

        code = str(error) if isinstance(error, ValueError) else "parser_launch_failed"
        print(
            json.dumps({"status": "partial", "code": code, "source_preserved": True}),
            file=sys.stderr,
        )
        return 2
