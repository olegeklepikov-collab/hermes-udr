"""Pin local configuration across one research process tree without copying secrets."""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .canonical import sha256_json

_ENV = "HERMES_RESEARCH_RUNTIME_SNAPSHOT"
_FILES = ("config.yaml", ".env", "auth.json")
_ROUTE_ENV = (
    "HERMES_RESEARCH_MODEL_CLASS",
    "HERMES_MANAGED_DIR",
    "HERMES_PROFILE",
    "HERMES_MODEL",
    "HERMES_PROVIDER",
    "OPENAI_BASE_URL",
    "OPENROUTER_BASE_URL",
    "HERMES_SAFE_MODE",
    "HERMES_IGNORE_USER_CONFIG",
    "HERMES_IGNORE_RULES",
)


# Inputs actually consumed by the bundled Hermes web/model routes or the local
# provider probes. Academic keyless adapters do not read OPENALEX_API_KEY.
# Presence and absence are both pinned: adding a credential can switch free/paid
# routing just as changing an existing credential can switch an account.
RUNTIME_INPUT_BINDINGS = {
    "web_provider": (
        "KEENABLE_API_KEY",
        "TAVILY_API_KEY",
        "EXA_API_KEY",
        "PARALLEL_API_KEY",
        "PERPLEXITY_API_KEY",
        "FIRECRAWL_API_KEY",
        "FIRECRAWL_API_URL",
        "FIRECRAWL_GATEWAY_URL",
        "BRAVE_SEARCH_API_KEY",
        "NIMBLE_API_KEY",
        "UNPAYWALL_EMAIL",
        "TOOL_GATEWAY_DOMAIN",
        "TOOL_GATEWAY_SCHEME",
        "TOOL_GATEWAY_USER_TOKEN",
    ),
    "model_provider": (
        "ACTUAL_API_KEY",
        "ACTUAL_BASE_URL",
        "AI_GATEWAY_API_KEY",
        "AI_GATEWAY_BASE_URL",
        "ALIBABA_CODING_PLAN_API_KEY",
        "ALIBABA_CODING_PLAN_BASE_URL",
        "ALIBABA_CODING_PLAN_CN_API_KEY",
        "ALIBABA_CODING_PLAN_CN_BASE_URL",
        "ALIBABA_TOKEN_PLAN_API_KEY",
        "ALIBABA_TOKEN_PLAN_BASE_URL",
        "ALIBABA_TOKEN_PLAN_CN_API_KEY",
        "ALIBABA_TOKEN_PLAN_CN_BASE_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_TOKEN",
        "ARCEEAI_API_KEY",
        "ARCEE_BASE_URL",
        "AZURE_ANTHROPIC_KEY",
        "AZURE_FOUNDRY_API_KEY",
        "AZURE_FOUNDRY_BASE_URL",
        "BEDROCK_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "COMMANDCODE_ANTHROPIC_BASE_URL",
        "COMMANDCODE_API_KEY",
        "COMMANDCODE_BASE_URL",
        "COPILOT_ACP_BASE_URL",
        "COPILOT_API_BASE_URL",
        "COPILOT_GITHUB_TOKEN",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_BASE_URL",
        "DASHSCOPE_CN_BASE_URL",
        "DEEPINFRA_API_KEY",
        "DEEPINFRA_BASE_URL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "FIREWORKS_API_KEY",
        "GEMINI_API_KEY",
        "GEMINI_BASE_URL",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GLM_API_KEY",
        "GLM_BASE_URL",
        "GMI_API_KEY",
        "GMI_BASE_URL",
        "GOOGLE_API_KEY",
        "HERMES_CODEX_BASE_URL",
        "HERMES_INFERENCE_PROVIDER",
        "HERMES_NOUS_TIMEOUT_SECONDS",
        "HF_BASE_URL",
        "HF_TOKEN",
        "KILOCODE_API_KEY",
        "KILOCODE_BASE_URL",
        "KIMI_API_KEY",
        "KIMI_BASE_URL",
        "KIMI_CN_API_KEY",
        "KIMI_CODING_API_KEY",
        "LM_API_KEY",
        "LM_BASE_URL",
        "META_API_KEY",
        "META_BASE_URL",
        "META_MODEL_API_KEY",
        "MINIMAX_API_KEY",
        "MINIMAX_BASE_URL",
        "MINIMAX_CN_API_KEY",
        "MINIMAX_CN_BASE_URL",
        "MODEL_API_KEY",
        "NEBIUS_API_KEY",
        "NEBIUS_BASE_URL",
        "NEBIUS_TOKEN_FACTORY_API_KEY",
        "NOVITA_API_KEY",
        "NOVITA_BASE_URL",
        "NVIDIA_API_KEY",
        "NVIDIA_BASE_URL",
        "OLLAMA_API_KEY",
        "OLLAMA_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENCODE_GO_API_KEY",
        "OPENCODE_GO_BASE_URL",
        "OPENCODE_ZEN_API_KEY",
        "OPENCODE_ZEN_BASE_URL",
        "OPENROUTER_API_KEY",
        "RAMP_ROUTER_API_KEY",
        "RAMP_ROUTER_BASE_URL",
        "ROUTER_API_KEY",
        "STEPFUN_API_KEY",
        "STEPFUN_BASE_URL",
        "TOKENHUB_API_KEY",
        "TOKENHUB_BASE_URL",
        "TOKENPLAN_API_KEY",
        "TOKENPLAN_BASE_URL",
        "UPSTAGE_API_KEY",
        "UPSTAGE_BASE_URL",
        "XAI_API_KEY",
        "XAI_BASE_URL",
        "XIAOMI_API_KEY",
        "XIAOMI_BASE_URL",
        "ZAI_API_KEY",
        "Z_AI_API_KEY",
    ),
    "transport": (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    ),
    "python_imports": ("PYTHONPATH", "PYTHONHOME"),
}


def _host_credential_name(url: str) -> str | None:
    # Mirrors the selected Hermes custom-endpoint reader; no DNS or request.
    try:
        hostname = urlsplit(url).hostname or ""
    except ValueError:
        return None
    if (
        not hostname
        or hostname == "localhost"
        or ":" in hostname
        or any(ch.isdigit() for ch in hostname.split(".")[-1])
    ):
        return None
    labels = [label for label in hostname.split(".") if label]
    while labels and labels[0] in ("api", "www"):
        labels.pop(0)
    vendor = (
        "".join(ch if ch.isalnum() else "_" for ch in labels[-2]).upper()
        if len(labels) >= 2
        else ""
    )
    return vendor + "_API_KEY" if vendor and vendor[0].isalpha() else None


def runtime_environment_names(references: set[str]) -> list[str]:
    names = (
        set(_ROUTE_ENV)
        | references
        | {key for values in RUNTIME_INPUT_BINDINGS.values() for key in values}
    )
    for name in tuple(names):
        if name.endswith("BASE_URL"):
            derived = _host_credential_name(os.environ.get(name, ""))
            if derived:
                names.add(derived)
    return sorted(names)


class RuntimeSnapshotError(ValueError):
    pass


def file_digest(path: Path, *, env_references: set[str] | None = None) -> str | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError:
        raise RuntimeSnapshotError("runtime_config_unreadable") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4_000_000:
            raise RuntimeSnapshotError("runtime_config_invalid")
        digest = hashlib.sha256()
        content = bytearray()
        size = 0
        while chunk := os.read(fd, 65536):
            size += len(chunk)
            if size > 4_000_000:
                raise RuntimeSnapshotError("runtime_config_invalid")
            digest.update(chunk)
            if env_references is not None:
                content.extend(chunk)
        after = os.fstat(fd)
        if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeSnapshotError("runtime_configuration_changed")
        if env_references is not None:
            env_references.update(
                match.decode("ascii")
                for match in re.findall(
                    rb"\$\{\s*(?:env:\s*)?([A-Za-z_][A-Za-z0-9_]*)(?:\s*|:-[^}]*)\}",
                    content,
                )
            )
        if env_references is not None:
            env_references.update(
                match.decode("ascii")
                for match in re.findall(
                    rb"(?:key_env|api_key_env)[\"\']?\s*:\s*[\"\']?([A-Za-z_][A-Za-z0-9_]*)",
                    content,
                )
            )
        if env_references is not None:
            for endpoint in re.findall(
                rb"(?:base_url|endpoint|[A-Z_]*BASE_URL)[\"\']?\s*[:=]\s*[\"\']?(https?://[^\s\"\']+)",
                content,
            ):
                derived = _host_credential_name(
                    endpoint.decode("utf-8", errors="replace")
                )
                if derived:
                    env_references.add(derived)
        return digest.hexdigest()
    finally:
        os.close(fd)


def managed_directory() -> Path | None:
    override = os.environ.get("HERMES_MANAGED_DIR", "").strip()
    if not override and "PYTEST_CURRENT_TEST" in os.environ:
        return None
    path = Path(override) if override else Path("/etc/hermes")
    if path.is_symlink() or not path.is_absolute():
        raise RuntimeSnapshotError("runtime_managed_root_invalid")
    return path if path.is_dir() else None


def capture_runtime() -> dict[str, Any]:
    home = os.environ.get("HERMES_HOME")
    files: dict[str, str | None] = {}
    references: set[str] = set()
    if home:
        root = Path(home)
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise RuntimeSnapshotError("runtime_home_invalid")
        for name in _FILES:
            files[name] = file_digest(
                root / name, env_references=references if name != "auth.json" else None
            )
    managed = managed_directory()
    managed_files = (
        {
            name: file_digest(managed / name, env_references=references)
            for name in ("config.yaml", ".env")
        }
        if managed
        else {}
    )
    return {
        "schema_version": 3,
        "environment_input_names": runtime_environment_names(references),
        "home_hash": sha256_json(home),
        "files": files,
        "managed_root_hash": sha256_json(str(managed) if managed else None),
        "managed_files": managed_files,
        "route_environment_hash": sha256_json(
            {key: os.environ.get(key) for key in runtime_environment_names(references)}
        ),
    }


def verify_runtime() -> str:
    current = capture_runtime()
    inherited = os.environ.get(_ENV)
    if inherited is not None:
        try:
            expected = json.loads(inherited)
        except (ValueError, TypeError):
            raise RuntimeSnapshotError("runtime_snapshot_invalid") from None
        if expected != current:
            raise RuntimeSnapshotError("runtime_configuration_changed")
    return sha256_json(current)


def runtime_guarded(function: Callable[..., Any]) -> Callable[..., Any]:
    """Scope inherited state to a CLI invocation; never leak it to another run."""

    @functools.wraps(function)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        from .turn_trace import ENV as TRACE_ENV
        from .turn_trace import finish_turn, profile_context

        inherited = os.environ.get(_ENV)
        trace_start = None
        entered = False
        return_code = 2
        try:
            trace_start = profile_context(function, args, kwargs)
            verify_runtime()
            if inherited is None:
                os.environ[_ENV] = json.dumps(capture_runtime(), sort_keys=True)
            entered = True
            result = function(*args, **kwargs)
            return_code = result if type(result) is int else 0
            return result
        except RuntimeSnapshotError as error:
            print(json.dumps({"status": "error", "code": str(error)}), file=sys.stderr)
            return 2
        except BaseException as error:
            return_code = (
                error.code
                if isinstance(error, SystemExit) and type(error.code) is int
                else 1
            )
            raise
        finally:
            try:
                if trace_start is not None:
                    finish_turn(trace_start, return_code, entered)
            finally:
                if trace_start is not None:
                    os.environ.pop(TRACE_ENV, None)
                if inherited is None:
                    os.environ.pop(_ENV, None)

    return guarded
