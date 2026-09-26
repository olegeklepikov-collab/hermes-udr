"""Run one explicitly configured native foreground process without logging secrets."""

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: service_exec.py ABSOLUTE_SPEC.json")
    spec_path = Path(sys.argv[1]).resolve(strict=True)
    spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    if not isinstance(spec, dict):
        raise SystemExit("Service specification must be an object")

    argv = spec.get("argv")
    if not isinstance(argv, list) or not argv or any(
        not isinstance(item, str) or not item for item in argv
    ):
        raise SystemExit("argv must be a nonempty list of strings")
    if not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file():
        raise SystemExit("argv[0] must be an absolute existing executable path")
    cwd_value = spec.get("cwd")
    if not isinstance(cwd_value, str) or not Path(cwd_value).is_absolute():
        raise SystemExit("cwd must be an absolute path")
    cwd = Path(cwd_value)
    if not cwd.is_dir():
        raise SystemExit("cwd must be an existing directory")

    extra_env = spec.get("env", {})
    if not isinstance(extra_env, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in extra_env.items()
    ):
        raise SystemExit("env must contain string names and values")
    env = os.environ.copy()
    env_file = spec.get("env_file")
    if env_file is not None:
        if (not isinstance(env_file, str) or not Path(env_file).is_absolute()
                or not Path(env_file).is_file()):
            raise SystemExit("env_file must be an absolute existing file")
        from dotenv import dotenv_values

        env.update({
            key: value for key, value in dotenv_values(env_file).items()
            if value is not None
        })
    env.update(extra_env)
    return subprocess.call(argv, cwd=cwd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
