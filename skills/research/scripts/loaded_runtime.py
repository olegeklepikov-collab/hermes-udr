"""Guard the actual one-shot configuration reader; persist only fingerprints."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any

try:
    from .file_io import write_exclusive_json
except ImportError:
    from file_io import write_exclusive_json

from hermes_research_report.canonical import sha256_json, with_receipt_hash
from hermes_research_report.runtime_snapshot import capture_runtime, managed_directory

RUNTIME_FAILURE_CODES = {
    "runtime_model_route_not_bounded",
    "vision_route_not_bounded",
    "runtime_configuration_changed",
    "runtime_loaded_configuration_changed",
    "runtime_loaded_config_invalid",
    "runtime_managed_config_invalid",
    "runtime_config_invalid",
    "runtime_config_unreadable",
    "runtime_home_invalid",
    "runtime_snapshot_invalid",
    "runtime_managed_root_invalid",
}


def record_runtime_failure(output: Path, error: Exception):
    code = (
        str(error)
        if str(error) in RUNTIME_FAILURE_CODES
        else "runtime_model_worker_failed"
    )
    write_exclusive_json(
        output / "effective-runtime-failure.json",
        with_receipt_hash(
            {
                "contract": "LoadedHermesRuntimeFailure",
                "reason_code": code,
                "model_entry_recorded": (
                    output / "effective-model-entry.json"
                ).is_file(),
                "raw_configuration_persisted": False,
            }
        ),
    )


def input_files(snapshot: dict) -> dict:
    # Bootstrap intentionally loads dotenv and sets safe-mode flags. Files stay pinned.
    return {
        key: value for key, value in snapshot.items() if key != "route_environment_hash"
    }


def effective_provider_inputs_hash() -> str:
    """Fingerprint the same scoped secret reader used by Hermes, without values."""
    names = capture_runtime()["environment_input_names"]
    module = sys.modules.get("agent.secret_scope")
    reader = getattr(module, "get_secret_str", None)
    try:
        values = {
            name: reader(name, "") if callable(reader) else os.environ.get(name, "")
            for name in names
        }
    except Exception:  # noqa: BLE001 — normalize errors from the external scoped credential reader.
        raise ValueError("runtime_loaded_configuration_changed") from None
    return sha256_json(values)


class LoadedRuntimeGuard:
    def __init__(self, config_module: Any, output: Path, initial_snapshot: dict):
        self.module = config_module
        self.output = output
        self.initial = initial_snapshot
        self.original = config_module.load_config
        self.readonly = getattr(config_module, "load_config_readonly", None)
        self._check_inputs()
        managed = managed_directory()
        if managed and (managed / "config.yaml").is_file():
            import yaml

            try:
                value = yaml.safe_load((managed / "config.yaml").read_text())
                if value is not None and not isinstance(value, dict):
                    raise ValueError("invalid managed object")
            except (OSError, ValueError, yaml.YAMLError):
                raise ValueError("runtime_managed_config_invalid") from None
        self.expected = sha256_json(self._load())
        self.effective_environment = capture_runtime()["route_environment_hash"]
        self.effective_provider_inputs = effective_provider_inputs_hash()
        module_file = getattr(config_module, "__file__", None)
        self.snapshot = with_receipt_hash(
            {
                "contract": "LoadedHermesRuntimeSnapshot",
                "initial_runtime_hash": sha256_json(initial_snapshot),
                "loaded_config_hash": self.expected,
                "effective_route_environment_hash": self.effective_environment,
                "desired_route_environment_hash": initial_snapshot[
                    "route_environment_hash"
                ],
                "effective_provider_inputs_hash": self.effective_provider_inputs,
                "environment_input_names": initial_snapshot["environment_input_names"],
                "config_module_sha256": hashlib.sha256(
                    Path(module_file).read_bytes()
                ).hexdigest()
                if module_file
                else None,
                "python_version": list(sys.version_info[:3]),
                "raw_configuration_persisted": False,
                "remote_provider_configuration_verified": False,
            }
        )
        write_exclusive_json(output / "effective-runtime.json", self.snapshot)
        config_module.load_config = self.load
        if self.readonly is not None:
            config_module.load_config_readonly = self.load

    def _check_inputs(self):
        current = capture_runtime()
        if input_files(current) != input_files(self.initial):
            raise ValueError("runtime_configuration_changed")
        return current

    def _load(self):
        config = self.original()
        diagnostic = getattr(self.module, "get_active_config_parse_failure", None)
        if callable(diagnostic) and diagnostic():
            raise ValueError("runtime_loaded_config_invalid")
        return config

    def load(self):
        current = self._check_inputs()
        if current["route_environment_hash"] != self.effective_environment:
            raise ValueError("runtime_configuration_changed")
        if effective_provider_inputs_hash() != self.effective_provider_inputs:
            raise ValueError("runtime_loaded_configuration_changed")
        config = self._load()
        if sha256_json(config) != self.expected:
            raise ValueError("runtime_loaded_configuration_changed")
        return config

    def before_model(self):
        self.load()
        write_exclusive_json(
            self.output / "effective-model-entry.json",
            with_receipt_hash(
                {
                    "contract": "LoadedHermesModelEntry",
                    "runtime_receipt_hash": self.snapshot["receipt_hash"],
                    "initial_runtime_hash": self.snapshot["initial_runtime_hash"],
                    "loaded_config_hash": self.expected,
                }
            ),
        )

    def restore(self):
        self.module.load_config = self.original
        if self.readonly is not None:
            self.module.load_config_readonly = self.readonly
