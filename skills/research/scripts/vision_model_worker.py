"""One native multimodal Hermes turn; no tools, hooks, fallback model, or shell actions."""

import base64
import contextlib
import hashlib
import io
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))


def main():
    from file_io import load_json, read_private_bytes, write_exclusive_json
    from loaded_runtime import LoadedRuntimeGuard

    from hermes_research_report.canonical import sha256_json, with_receipt_hash
    from hermes_research_report.runtime_snapshot import capture_runtime, verify_runtime

    verify_runtime()
    initial = capture_runtime()
    attempt, _ = load_json(Path(sys.argv[1]).parent / "attempt.json")
    if attempt.get("runtime_snapshot_hash") != sha256_json(initial):
        raise ValueError("runtime_configuration_changed")
    os.environ["HERMES_SAFE_MODE"] = "1"
    os.environ["HERMES_IGNORE_USER_CONFIG"] = "1"
    os.environ["HERMES_IGNORE_RULES"] = "1"

    request = json.loads(read_private_bytes(Path(sys.argv[1]), maximum=2_000_000))
    if (
        request.get("provider"), request.get("model"), request.get("reasoning"),
        request.get("requested_model_class"), request.get("model_class_mapping_hash"),
        request.get("model_route_source"), request.get("model_class_selection_source"),
    ) != (
        attempt.get("provider"), attempt.get("model"), attempt.get("reasoning"),
        attempt.get("requested_model_class"), attempt.get("model_class_mapping_hash"),
        attempt.get("model_route_source"), attempt.get("model_class_selection_source"),
    ):
        raise ValueError("vision_route_not_bounded")
    image = read_private_bytes(Path(request["image"]), maximum=8_000_000)
    if not image.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("vision_png_required")
    logging.disable(logging.CRITICAL)
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        from hermes_cli.env_loader import load_hermes_dotenv

        load_hermes_dotenv(hermes_home=os.environ["HERMES_HOME"])
        from hermes_cli import config

        guard = LoadedRuntimeGuard(config, Path(sys.argv[1]).parent, initial)
        from hermes_cli.fallback_config import get_fallback_chain
        from model_tools import get_tool_definitions

        if get_fallback_chain(config.load_config()) or get_tool_definitions(
            enabled_toolsets=["context_engine"], quiet_mode=True
        ):
            raise ValueError("vision_route_not_bounded")
        from gateway.session_context import declare_stateless_channel

        declare_stateless_channel()
        from hermes_cli.oneshot import _USAGE_KEYS, _run_agent

        parts = [
            {"type": "text", "text": request["prompt"]},
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(image).decode()
                },
            },
        ]
        input_receipt = with_receipt_hash(
            {
                "contract": "HermesNativeImageInput",
                "prompt_sha256": hashlib.sha256(request["prompt"].encode()).hexdigest(),
                "image_sha256": hashlib.sha256(image).hexdigest(),
                "content_parts_sha256": sha256_json(parts),
                "content_types": [p["type"] for p in parts],
                "provider": request["provider"],
                "model": request["model"],
                "requested_model_class": request["requested_model_class"],
                "model_class_selection_source": request["model_class_selection_source"],
                "model_class_mapping_hash": request["model_class_mapping_hash"],
            }
        )
        write_exclusive_json(
            Path(sys.argv[1]).parent / "vision-input.json", input_receipt
        )
        guard.before_model()
        response, result = _run_agent(
            parts,
            model=request["model"],
            provider=request["provider"],
            toolsets=["context_engine"],
            use_config_toolsets=False,
            reasoning=request["reasoning"],
        )
    usage = {key: result.get(key) for key in _USAGE_KEYS}
    usage["failed"] = bool(result.get("failed"))
    write_exclusive_json(Path(request["usage_file"]), usage)
    write_exclusive_json(
        Path(sys.argv[1]).parent / "vision-observation.json",
        with_receipt_hash(
            {
                "contract": "HermesNativeImageObservation",
                "input_receipt_hash": input_receipt["receipt_hash"],
                "session_id": usage["session_id"],
                "response_sha256": hashlib.sha256(
                    response.strip().encode()
                ).hexdigest(),
                "request_binding_basis": "native_content_parts_worker_receipt_not_provider_attestation",
            }
        ),
    )
    print(response)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 — process boundary must not expose credential-bearing provider errors.
        from loaded_runtime import record_runtime_failure

        with contextlib.suppress(OSError, ValueError, IndexError):
            record_runtime_failure(Path(sys.argv[1]).parent, error)
        print("vision_model_worker_failed", file=sys.stderr)
        raise SystemExit(2) from None
