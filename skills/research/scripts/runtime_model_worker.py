"""Execute the configured Hermes Python entry point with a pinned config reader."""

import contextlib
import importlib
import logging
import os
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))


def main():
    from file_io import load_json
    from loaded_runtime import LoadedRuntimeGuard, record_runtime_failure

    from hermes_research_report.canonical import sha256_json
    from hermes_research_report.runtime_snapshot import capture_runtime, verify_runtime

    verify_runtime()
    initial = capture_runtime()
    output, entrypoint = Path(sys.argv[1]), Path(sys.argv[2])
    attempt, _ = load_json(output / "attempt.json")
    if attempt.get("runtime_snapshot_hash") != sha256_json(initial):
        raise ValueError("runtime_configuration_changed")
    for key in ("HERMES_SAFE_MODE", "HERMES_IGNORE_USER_CONFIG", "HERMES_IGNORE_RULES"):
        os.environ[key] = "1"
    arguments = sys.argv[3:]
    try:
        route = (
            arguments[arguments.index("--provider") + 1],
            arguments[arguments.index("-m") + 1],
            arguments[arguments.index("--reasoning") + 1],
        )
    except (ValueError, IndexError):
        raise ValueError("runtime_model_route_not_bounded") from None
    if route != (
        attempt.get("provider"),
        attempt.get("model"),
        attempt.get("reasoning"),
    ):
        raise ValueError("runtime_model_route_not_bounded")
    logging.disable(logging.CRITICAL)
    with contextlib.redirect_stdout(sys.stderr):
        importlib.import_module(
            "hermes_cli.main"
        )  # Preserve CLI dotenv bootstrap before pinning.
        from hermes_cli import config, oneshot
    guard = LoadedRuntimeGuard(config, output, initial)
    original = oneshot._run_agent

    def guarded_agent(*args, **kwargs):
        from hermes_cli.fallback_config import get_fallback_chain
        from model_tools import get_tool_definitions

        try:
            if get_fallback_chain(guard.load()) or get_tool_definitions(
                enabled_toolsets=["context_engine"], quiet_mode=True
            ):
                raise ValueError("runtime_model_route_not_bounded")
            guard.before_model()
        except ValueError as error:
            # Hermes can consume this exception; persist the safe reason before handing it back.
            record_runtime_failure(output, error)
            raise
        return original(*args, **kwargs)

    oneshot._run_agent = guarded_agent
    sys.argv = [str(entrypoint), *arguments]
    runpy.run_path(str(entrypoint), run_name="__main__")


if __name__ == "__main__":
    failure_output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    try:
        main()
    except Exception as error:  # noqa: BLE001 — do not disclose credential-bearing bootstrap errors.
        from loaded_runtime import record_runtime_failure

        with contextlib.suppress(OSError, ValueError, IndexError):
            if failure_output is not None:
                record_runtime_failure(failure_output, error)
        print("runtime_model_worker_failed", file=sys.stderr)
        raise SystemExit(2) from None
