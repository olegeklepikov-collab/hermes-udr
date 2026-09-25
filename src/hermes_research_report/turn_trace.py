"""Content-free managed-turn journal over existing receipt files, not a second store."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
import uuid
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path

from .canonical import sha256_json, verify_receipt_hash, with_receipt_hash

ENV = "HERMES_RESEARCH_TURN_TRACE"
STAGES = (
    "channel",
    "run",
    "work",
    "context",
    "operation",
    "evidence",
    "commit",
    "delivery",
)
PROFILES = {
    "run_beta_search": "search",
    "run_beta_deep_question": "deep",
    "run_beta_deep": "deep",
    "run_beta_research": "research",
}
HASH = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[0-9a-f]{32}$")
SAFE_REF = re.compile(r"^[A-Za-z0-9_.:/-]+$")
STAGE_CONTRACTS = {
    "channel": frozenset({"TelegramSessionBindingReceipt"}),
    "run": frozenset({"BetaModeExecutionPlan", "ManagedTurnRunReceipt"}),
    "work": frozenset(
        {
            "BeadsCreateReceipt",
            "BeadsReadReceipt",
            "BeadsClaimReceipt",
            "BeadsCloseReceipt",
        }
    ),
    "context": frozenset(
        {
            "LoadedHermesRuntimeSnapshot",
            "LoadedHermesSourceRuntime",
            "ContextContributionReceipt",
            "ZvecQueryReceipt",
            "TurnContextReadback",
            "ArtifactIngestReceipt",
        }
    ),
    "operation": frozenset(
        {
            "LoadedHermesModelEntry",
            "LeaseDecisionReceipt",
            "FoundationHookReceipt",
            "OutboxDecisionReceipt",
            "DoltStateWriteReceipt",
            "AttemptRecord",
        }
    ),
    "evidence": frozenset(
        {
            "FoundFragmentRecordReceipt",
            "SourceFragmentDecisionReceipt",
            "BetaSourceAcquisition",
        }
    ),
    "commit": frozenset({"DoltStateWriteReceipt"}),
    "delivery": frozenset({"LocalArtifactDeliveryReceipt", "TransportReceipt"}),
}
CONTRACT_STAGES = {
    contract: stage
    for stage, contracts in STAGE_CONTRACTS.items()
    for contract in contracts
}
FAILURE_STATES = frozenset({"failed", "blocked", "stale_revision", "lease_conflict"})


PROFILE_OUTCOMES = frozenset(
    {
        "BetaAutonomousSearchRun",
        "BetaAutonomousDeepRun",
        "BetaAutonomousDeepQuestionRun",
        "BetaAutonomousProfileDossier",
    }
)
SOURCE_RECEIPTS = frozenset(
    {
        "BetaSourceAcquisition",
        "BetaOpenAlexMetadataAcquisition",
        "BetaArxivMetadataAcquisition",
        "BetaDataCiteDatasetMetadataAcquisition",
    }
)
STANDALONE_CONTRACT = {
    "kind": "standalone_local_research",
    "beads_work_executed": False,
    "dolt_commit_executed": False,
    "external_delivery_executed": False,
}
STAGE_CONTRACTS["run"] |= PROFILE_OUTCOMES
STAGE_CONTRACTS["operation"] |= SOURCE_RECEIPTS | {"BetaAutomaticSourceExecution"}
STAGE_CONTRACTS["evidence"] |= SOURCE_RECEIPTS | {"BetaSourcePortfolio"}
CONTRACT_STAGES = {
    contract: stage
    for stage, contracts in STAGE_CONTRACTS.items()
    for contract in contracts
}
_LAST_READ: dict[str, str] = {}
_LAST_CONTEXT: dict[str, str] = {}


def _write(path: Path, value: dict) -> None:
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("trace_path_unsafe")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _load(path: Path) -> tuple[dict, str]:
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("trace_path_unsafe")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4_000_000:
            raise ValueError("trace_file_invalid")
        raw = stream.read(4_000_001)

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("trace_duplicate_key")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise TypeError("trace_object_required")
    return value, hashlib.sha256(raw).hexdigest()


def _context() -> tuple[Path, str] | None:
    raw = os.environ.get(ENV)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
        root = Path(value["output_root"])
        turn = value["turn_id"]
        if (
            set(value) != {"output_root", "turn_id"}
            or not ID.fullmatch(turn)
            or not root.is_absolute()
            or root.is_symlink()
            or not root.is_dir()
        ):
            raise ValueError()
        if any(parent.is_symlink() for parent in root.parents):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError("turn_trace_context_invalid") from None
    return root, turn


def _area(root: Path, turn: str) -> Path:
    return root / ".managed-turns" / "turns" / turn


def _child_registration(root: Path, turn: str, child_run_ref: str) -> Path:
    return _area(root, turn) / "child-runs" / (child_run_ref + ".json")


def _trusted_child(
    root: Path, turn: str, child_run_ref: str, anchor: dict
) -> bool:
    path = _child_registration(root, turn, child_run_ref)
    if not path.is_file() or path.is_symlink():
        return False
    try:
        registration, _ = _load(path)
        start, _ = _load(root / ".managed-turns" / "starts" / (turn + ".json"))
    except (OSError, ValueError, TypeError):
        return False
    return (
        verify_receipt_hash(registration)
        and verify_receipt_hash(start)
        and registration.get("contract") == "ManagedTurnChildRunRegistration"
        and registration.get("turn_id") == turn
        and registration.get("start_receipt_hash") == start.get("receipt_hash")
        and registration.get("parent_run_ref") == anchor.get("run_ref")
        and registration.get("anchor_receipt_hash") == anchor.get("receipt_hash")
        and registration.get("child_run_ref") == child_run_ref
    )


def register_child_run(parent_run_id: str, child_run_id: str) -> None:
    """Admit one exact child before its subprocess can write a run receipt."""
    context = _context()
    if context is None:
        raise ValueError("turn_trace_context_missing")
    root, turn = context
    if (
        not isinstance(parent_run_id, str)
        or not SAFE_REF.fullmatch(parent_run_id)
        or not isinstance(child_run_id, str)
        or not SAFE_REF.fullmatch(child_run_id)
        or child_run_id == parent_run_id
    ):
        raise ValueError("turn_child_run_invalid")
    anchor, _ = _load(_area(root, turn) / "run-anchor.json")
    if (
        not verify_receipt_hash(anchor)
        or anchor.get("contract") != "ManagedTurnRunAnchor"
        or anchor.get("turn_id") != turn
        or anchor.get("run_ref") != sha256_json(parent_run_id)
    ):
        raise ValueError("turn_child_parent_unbound")
    child_run_ref = sha256_json(child_run_id)
    path = _child_registration(root, turn, child_run_ref)
    if path.exists():
        raise ValueError("turn_child_already_registered")
    _write(
        path,
        with_receipt_hash(
            {
                "contract": "ManagedTurnChildRunRegistration",
                "turn_id": turn,
                "start_receipt_hash": _load(
                    root / ".managed-turns" / "starts" / (turn + ".json")
                )[0]["receipt_hash"],
                "parent_run_ref": anchor["run_ref"],
                "anchor_receipt_hash": anchor["receipt_hash"],
                "child_run_ref": child_run_ref,
            }
        ),
    )


def begin_turn(
    output_root: Path,
    profile: str,
    argument_hash: str,
    *,
    execution_kind: str = "explicit_managed",
) -> dict:
    root = output_root.resolve()
    if not output_root.is_absolute() or output_root.is_symlink() or not root.is_dir():
        raise ValueError("turn_trace_root_invalid")
    if (root / ".managed-turns").is_symlink():
        raise ValueError("turn_trace_root_invalid")
    turn = uuid.uuid4().hex
    start = with_receipt_hash(
        {
            "contract": "ManagedTurnStart",
            "turn_id": turn,
            "profile": profile,
            "channel": "local_cli",
            "execution_kind": execution_kind,
            "argument_hash": argument_hash,
            "status": "started",
            "started_ns": time.time_ns(),
        }
    )
    # This durable admission precedes the first operation. Missing finish stays in the denominator.
    _write(root / ".managed-turns" / "starts" / (turn + ".json"), start)
    _area(root, turn).mkdir(parents=True, exist_ok=False, mode=0o700)
    os.environ[ENV] = json.dumps(
        {"output_root": str(root), "turn_id": turn}, sort_keys=True
    )
    return start


def profile_context(function, args, kwargs) -> dict | None:
    if os.environ.get(ENV) is not None:
        return None
    profile = PROFILES.get(Path(function.__code__.co_filename).stem)
    if profile is None:
        return None
    argv = kwargs.get("argv", args[0] if args else None)
    argv = list(argv) if argv is not None else list(__import__("sys").argv[1:])
    if any(arg in ("-h", "--help") for arg in argv) or "--public-query-ack" not in argv:
        return None

    def flag(name):
        for index, arg in enumerate(argv):
            if arg == name:
                return argv[index + 1] if index + 1 < len(argv) else None
            if arg.startswith(name + "="):
                return arg[len(name) + 1 :]
        return None

    output = flag("--output-root")
    if output is None:
        return None  # argparse rejects a non-admitted invocation.
    output_path = Path(output)
    if (
        not output_path.is_absolute()
        or output_path.is_symlink()
        or not output_path.is_dir()
    ):
        return None  # The original entrypoint rejects an invalid, non-admitted root.
    if profile == "research":
        selected_mode = flag("--mode")
        profile = (
            selected_mode
            if isinstance(selected_mode, str) and selected_mode in {"ultra", "academic"}
            else "research"
        )
    return begin_turn(
        Path(output), profile, sha256_json(argv), execution_kind="standalone_profile"
    )


def finish_turn(start: dict, return_code: int, entered: bool) -> None:
    context = _context()
    if context is None:
        raise ValueError("turn_trace_context_missing")
    root, turn = context
    _write(
        _area(root, turn) / "finish.json",
        with_receipt_hash(
            {
                "contract": "ManagedTurnFinish",
                "turn_id": turn,
                "start_receipt_hash": start["receipt_hash"],
                "status": "returned" if return_code == 0 else "failed",
                "return_code": return_code,
                "function_entered": entered,
                "finished_ns": time.time_ns(),
            }
        ),
    )

    assessment = assess_turn(
        root, root / ".managed-turns" / "starts" / (turn + ".json")
    )
    _write(
        _area(root, turn) / "assessment.json",
        with_receipt_hash({"contract": "ManagedTurnTraceAssessment", **assessment}),
    )
    _LAST_READ.pop(turn, None)
    _LAST_CONTEXT.pop(turn, None)


def _parents(value: object) -> list[str]:
    result = set()

    def visit(item, depth=0):
        if depth > 30:
            return
        if isinstance(item, dict):
            for key, val in item.items():
                if (
                    isinstance(key, str)
                    and key.endswith("receipt_hash")
                    and isinstance(val, str)
                    and HASH.fullmatch(val)
                ):
                    result.add(val)
                elif key in (
                    "parent_receipt_refs",
                    "evidence_receipt_refs",
                ) and isinstance(val, list):
                    result.update(
                        v for v in val if isinstance(v, str) and HASH.fullmatch(v)
                    )
                elif isinstance(val, (dict, list)):
                    visit(val, depth + 1)
        elif isinstance(item, list):
            for val in item:
                visit(val, depth + 1)

    visit(value)
    if isinstance(value, dict):
        result.discard(value.get("receipt_hash"))
    return sorted(result)


def _run_value(value: dict):
    run = value.get("run_id", value.get("model_run_id"))
    if run is None and value.get("contract") == "DoltStateWriteReceipt":
        matches = re.findall(
            r"(?:^| )run:([A-Za-z0-9_.:-]+)(?: |$)", value.get("commit_message", "")
        )
        return matches[0] if len(matches) == 1 else None
    return run


def _run_hash(value: dict):
    if (
        value.get("contract") == "LocalArtifactDeliveryReceipt"
        and isinstance(value.get("run_ref"), str)
        and HASH.fullmatch(value["run_ref"])
    ):
        return value["run_ref"]
    run = _run_value(value)
    return sha256_json(run) if isinstance(run, str) else None


def _native_commit(value: dict) -> bool:
    return (
        value.get("contract") == "DoltStateWriteReceipt"
        and value.get("status") == "committed"
        and value.get("commit_created") is True
        and value.get("readback_verified") is True
        and isinstance(value.get("commit_ref"), str)
        and re.fullmatch(r"[0-9a-v]{32}", value["commit_ref"]) is not None
    )


def _referenced_bytes_hash(root: Path, ref: str) -> str:
    part = Path(ref)
    if part.is_absolute() or ".." in part.parts or not SAFE_REF.fullmatch(ref):
        raise ValueError("trace_material_ref_invalid")
    path = root / part
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("trace_path_unsafe")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    digest = hashlib.sha256()
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("trace_material_invalid")
        while block := stream.read(65536):
            digest.update(block)
    return digest.hexdigest()


def artifact_written(
    path: Path, value: object, file_hash: str, *, from_read: bool = False
) -> None:
    context = _context()
    if context is None or not isinstance(value, dict):
        return
    root, turn = context
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        if from_read:
            return
        raise ValueError("turn_artifact_outside_root")
    relative = resolved.relative_to(root).as_posix()
    if relative.startswith(".managed-turns/"):
        return
    if not SAFE_REF.fullmatch(relative):
        raise ValueError("turn_artifact_reference_not_content_free")
    contract = value.get("contract")
    stage = CONTRACT_STAGES.get(contract) if isinstance(contract, str) else None
    if stage is None and path.name == "attempt.json":
        stage = "operation"
    # Only typed receipts or actual attempt records enter the content-free graph.
    if stage is None and not verify_receipt_hash(value):
        return
    if contract is not None and not verify_receipt_hash(value):
        raise ValueError("turn_artifact_receipt_invalid")
    if stage == "commit" and not _native_commit(value):
        stage = "operation"
    event = with_receipt_hash(
        {
            "contract": "ManagedTurnArtifact",
            "turn_id": turn,
            "stage": stage,
            "artifact_ref": relative,
            "artifact_sha256": file_hash,
            "artifact_receipt_hash": value.get("receipt_hash"),
            "source_contract": (contract or "AttemptRecord")
            if stage is not None
            else None,
            "source_contract_hash": sha256_json(contract) if stage is None else None,
            "run_ref": _run_hash(value),
            "parent_receipt_refs": sorted(
                set(_parents(value))
                | {
                    _load(root / ".managed-turns" / "starts" / (turn + ".json"))[0][
                        "receipt_hash"
                    ]
                }
            ),
            "observed_ns": time.time_ns(),
        }
    )
    if not from_read:
        for ref in (_LAST_READ.get(turn), _LAST_CONTEXT.get(turn)):
            if ref and ref != event["artifact_receipt_hash"]:
                event["parent_receipt_refs"] = sorted(
                    set(event["parent_receipt_refs"]) | {ref}
                )
        event.pop("receipt_hash")
        event = with_receipt_hash(event)
    anchor_path = _area(root, turn) / "run-anchor.json"
    anchor = _load(anchor_path)[0] if anchor_path.exists() else None
    if anchor and event["run_ref"] and event["run_ref"] != anchor["run_ref"]:
        if _trusted_child(root, turn, event["run_ref"], anchor):
            event.pop("receipt_hash")
            event["parent_run_ref"] = anchor["run_ref"]
            event = with_receipt_hash(event)
        elif stage == "run":
            raise ValueError("turn_run_conflict")
    if stage == "run" and anchor is None:
        _write(
            anchor_path,
            with_receipt_hash(
                {
                    "contract": "ManagedTurnRunAnchor",
                    "turn_id": turn,
                    "run_ref": event["run_ref"],
                    "artifact_receipt_hash": event["artifact_receipt_hash"],
                }
            ),
        )
    _write(_area(root, turn) / "events" / (uuid.uuid4().hex + ".json"), event)
    if stage == "context" and event["artifact_receipt_hash"]:
        _LAST_CONTEXT[turn] = event["artifact_receipt_hash"]
    if from_read and event["artifact_receipt_hash"]:
        _LAST_READ[turn] = event["artifact_receipt_hash"]
    if not from_read and contract in SOURCE_RECEIPTS:
        observe_stage(
            "operation", path, value, parent_receipt_refs=event["parent_receipt_refs"]
        )
    if not from_read and contract in PROFILE_OUTCOMES:
        _profile_completion(root, turn, path, value)


def observe_stage(
    stage: str,
    receipt_path: Path,
    value: dict,
    *,
    parent_receipt_refs: Sequence[str] = (),
) -> None:
    """Bind a real native receipt not covered by the standard contract table."""
    if stage not in STAGES:
        raise ValueError("turn_stage_invalid")
    if value.get("contract") not in STAGE_CONTRACTS[stage]:
        raise ValueError("turn_stage_contract_mismatch")
    if stage == "commit" and not _native_commit(value):
        raise ValueError("turn_commit_not_observed")
    context = _context()
    if context is None:
        raise ValueError("turn_trace_context_missing")
    root, turn = context
    actual, digest = _load(receipt_path)
    if actual != value or not verify_receipt_hash(actual):
        raise ValueError("turn_stage_receipt_unbound")
    ref = receipt_path.resolve().relative_to(root).as_posix()
    if not SAFE_REF.fullmatch(ref):
        raise ValueError("turn_artifact_reference_not_content_free")
    _write(
        _area(root, turn) / "events" / (uuid.uuid4().hex + ".json"),
        with_receipt_hash(
            {
                "contract": "ManagedTurnArtifact",
                "turn_id": turn,
                "stage": stage,
                "artifact_ref": ref,
                "artifact_sha256": digest,
                "artifact_receipt_hash": value["receipt_hash"],
                "source_contract": value["contract"],
                "run_ref": _run_hash(value),
                "parent_receipt_refs": sorted(
                    set(parent_receipt_refs) | set(_parents(value))
                ),
                "observed_ns": time.time_ns(),
            }
        ),
    )


def _profile_completion(root: Path, turn: str, path: Path, value: dict) -> None:
    start, _ = _load(root / ".managed-turns" / "starts" / (turn + ".json"))
    if (
        start.get("execution_kind") != "standalone_profile"
        or value.get("execution_contract") != STANDALONE_CONTRACT
    ):
        return
    scope = with_receipt_hash(
        {
            "contract": "StandaloneTurnScope",
            "turn_id": turn,
            "outcome_receipt_ref": value["receipt_hash"],
            "not_executed_stages": ["work", "commit"],
            "external_delivery": "not_executed",
        }
    )
    scope_path = (
        _area(root, turn) / "profile-scopes" / (value["receipt_hash"] + ".json")
    )
    if not scope_path.exists():
        _write(scope_path, scope)
    target = path.parent / "result.md"
    if target.is_file() and not target.is_symlink():
        ref = target.relative_to(root).as_posix()
        local = with_receipt_hash(
            {
                "contract": "LocalArtifactDeliveryReceipt",
                "run_ref": _run_hash(value),
                "target_ref": ref,
                "target_sha256": _referenced_bytes_hash(root, ref),
                "parent_receipt_hash": value["receipt_hash"],
                "delivery_kind": "local_file",
                "remote_message_sent": False,
            }
        )
        local_path = (
            _area(root, turn) / "local-output" / (local["receipt_hash"] + ".json")
        )
        if not local_path.exists():
            _write(local_path, local)
            observe_stage(
                "delivery",
                local_path,
                local,
                parent_receipt_refs=[value["receipt_hash"]],
            )


def artifact_read(path: Path, value: object, file_hash: str) -> None:
    artifact_written(path, value, file_hash, from_read=True)


def record_unexecuted(stages: list[str], failure_receipt_ref: str) -> None:
    """A producer stopping after a real failed operation declares the untouched suffix."""
    context = _context()
    if (
        context is None
        or not HASH.fullmatch(failure_receipt_ref)
        or any(stage not in STAGES for stage in stages)
    ):
        raise ValueError("turn_stop_invalid")
    root, turn = context
    failed = []
    for path in (_area(root, turn) / "events").glob("*.json"):
        event, _ = _load(path)
        if event.get("artifact_receipt_hash") == failure_receipt_ref:
            material, digest = _load(root / event["artifact_ref"])
            if (
                verify_receipt_hash(event)
                and digest == event["artifact_sha256"]
                and verify_receipt_hash(material)
                and material.get("status") in FAILURE_STATES
                and material.get("contract") in STAGE_CONTRACTS.get(event["stage"], ())
            ):
                failed.append(STAGES.index(event["stage"]))
    if not failed or set(stages) != set(STAGES[max(failed) + 1 :]):
        raise ValueError("turn_unexecuted_not_failed_suffix")
    _write(
        _area(root, turn) / "unexecuted.json",
        with_receipt_hash(
            {
                "contract": "ManagedTurnUnexecutedSuffix",
                "turn_id": turn,
                "stages": sorted(set(stages)),
                "failure_receipt_ref": failure_receipt_ref,
                "status": "not_executed",
            }
        ),
    )


def assess_turn(root: Path, start_path: Path) -> dict:
    start, _ = _load(start_path)
    if not verify_receipt_hash(start):
        raise ValueError("turn_start_invalid")
    turn = start["turn_id"]
    area = _area(root, turn)
    issues = []
    events = []
    material_by_receipt = {}
    known = {start["receipt_hash"]}
    anchor = (
        _load(area / "run-anchor.json")[0]
        if (area / "run-anchor.json").is_file()
        else None
    )
    if anchor and not verify_receipt_hash(anchor):
        issues.append("run_anchor_invalid")
    for path in sorted((area / "events").glob("*.json")):
        event, _ = _load(path)
        if (
            not verify_receipt_hash(event)
            or event.get("turn_id") != turn
            or event.get("stage") not in (*STAGES, None)
        ):
            issues.append("event_unbound")
            continue
        try:
            ref = Path(event["artifact_ref"])
            if ref.is_absolute() or ".." in ref.parts:
                raise ValueError()
            actual, digest = _load(root / ref)
            actual_contract = actual.get("contract") or "AttemptRecord"
            if event["stage"] is None:
                if event.get("source_contract") is not None or event.get(
                    "source_contract_hash"
                ) != sha256_json(actual.get("contract")):
                    raise ValueError()
            elif (
                event["source_contract"] != actual_contract
                or actual_contract not in STAGE_CONTRACTS[event["stage"]]
            ):
                raise ValueError()
            if (
                digest != event["artifact_sha256"]
                or actual.get("receipt_hash") != event["artifact_receipt_hash"]
                or (actual.get("contract") and not verify_receipt_hash(actual))
            ):
                raise ValueError()
            if not set(_parents(actual)).issubset(event["parent_receipt_refs"]):
                issues.append(
                    "declared_parent_missing:" + (event["stage"] or "supporting")
                )
            if event["run_ref"] != _run_hash(actual):
                raise ValueError()
            if event["stage"] == "commit" and not _native_commit(actual):
                raise ValueError()
            if (
                actual.get("contract") == "TurnContextReadback"
                and _referenced_bytes_hash(root, actual["source_ref"])
                != actual["source_sha256"]
            ):
                raise ValueError()
            if actual.get("contract") == "LocalArtifactDeliveryReceipt":
                if (
                    actual.get("delivery_kind") != "local_file"
                    or actual.get("remote_message_sent") is not False
                ):
                    raise ValueError()
                if (
                    _referenced_bytes_hash(root, actual["target_ref"])
                    != actual["target_sha256"]
                ):
                    raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            issues.append("artifact_unbound:" + (event["stage"] or "supporting"))
            continue
        mismatched_run = (
            anchor
            and event["run_ref"]
            and event["run_ref"] != anchor["run_ref"]
        )
        trusted_child = bool(
            anchor is not None
            and mismatched_run
            and event.get("parent_run_ref") == anchor["run_ref"]
            and _trusted_child(root, turn, event["run_ref"], anchor)
        )
        if event.get("parent_run_ref") is not None and not trusted_child:
            issues.append("child_run_unbound:" + (event["stage"] or "supporting"))
        if (
            mismatched_run
            and event["source_contract"] not in {"AttemptRecord", None}
            and not trusted_child
        ):
            issues.append("run_id_mismatch:" + (event["stage"] or "supporting"))
        events.append(event)
        material_by_receipt[event["artifact_receipt_hash"]] = actual
        if event["artifact_receipt_hash"]:
            known.add(event["artifact_receipt_hash"])
    for event in events:
        if any(ref not in known for ref in event["parent_receipt_refs"]):
            issues.append("parent_receipt_missing:" + (event["stage"] or "supporting"))
    finish = None
    if (area / "finish.json").is_file():
        finish, _ = _load(area / "finish.json")
        if (
            not verify_receipt_hash(finish)
            or finish.get("turn_id") != turn
            or finish.get("start_receipt_hash") != start["receipt_hash"]
        ):
            issues.append("finish_unbound")
    else:
        issues.append("finish_missing")
    by_stage = {
        stage: [
            e["artifact_receipt_hash"] or e["artifact_sha256"]
            for e in events
            if e["stage"] == stage
        ]
        for stage in STAGES
    }
    by_stage["channel"].insert(0, start["receipt_hash"])
    declared_unexecuted = set()
    if (area / "unexecuted.json").is_file():
        declaration, _ = _load(area / "unexecuted.json")
        failure = material_by_receipt.get(declaration.get("failure_receipt_ref"), {})
        if (
            not verify_receipt_hash(declaration)
            or declaration.get("turn_id") != turn
            or failure.get("status") not in FAILURE_STATES
        ):
            issues.append("unexecuted_suffix_unbound")
        else:
            failed_stages = [
                STAGES.index(event["stage"])
                for event in events
                if event["artifact_receipt_hash"] == declaration["failure_receipt_ref"]
            ]
            declared_unexecuted = set(declaration["stages"])
            if not failed_stages or declared_unexecuted != set(
                STAGES[max(failed_stages) + 1 :]
            ):
                issues.append("unexecuted_not_failed_suffix")
            if any(
                stage not in STAGES or by_stage[stage] for stage in declared_unexecuted
            ):
                issues.append("stage_execution_contradiction")
    standalone_scopes = 0
    for scope_path in (area / "profile-scopes").glob("*.json"):
        scope, _ = _load(scope_path)
        outcome = material_by_receipt.get(scope.get("outcome_receipt_ref"), {})
        if (
            not verify_receipt_hash(scope)
            or scope.get("turn_id") != turn
            or start.get("execution_kind") != "standalone_profile"
            or outcome.get("contract") not in PROFILE_OUTCOMES
            or outcome.get("execution_contract") != STANDALONE_CONTRACT
            or scope.get("not_executed_stages") != ["work", "commit"]
        ):
            issues.append("standalone_scope_unbound")
        elif by_stage["work"] or by_stage["commit"]:
            issues.append("standalone_scope_contradicted")
        else:
            standalone_scopes += 1
            declared_unexecuted.update({"work", "commit"})
    stages = []
    for stage in STAGES:
        status = (
            "observed"
            if by_stage[stage]
            else "not_executed"
            if stage in declared_unexecuted
            or (finish and not finish["function_entered"])
            else "unknown"
        )
        stages.append(
            {"stage": stage, "status": status, "receipt_refs": by_stage[stage]}
        )
    parents_by_ref = {}
    for event in events:
        ref = event["artifact_receipt_hash"] or event["artifact_sha256"]
        parents_by_ref.setdefault(ref, set()).update(event["parent_receipt_refs"])

    def linked(previous_refs, current_refs):
        pending = list(current_refs)
        seen = set()
        while pending:
            ref = pending.pop()
            if ref in previous_refs:
                return True
            if ref not in seen:
                seen.add(ref)
                pending.extend(parents_by_ref.get(ref, ()))
        return False

    active = [stage for stage in STAGES if by_stage[stage]]
    chain = [
        {
            "from_stage": previous,
            "to_stage": current,
            "linked": linked(set(by_stage[previous]), by_stage[current]),
        }
        for previous, current in pairwise(active)
    ]
    if any(not edge["linked"] for edge in chain):
        issues.append("stage_chain_incomplete")
    return {
        "standalone_profile_scope_verified": standalone_scopes > 0,
        "all_stages_accounted": all(s["status"] != "unknown" for s in stages),
        "stage_edges": chain,
        "turn_id": turn,
        "profile": start["profile"],
        "execution_kind": start.get("execution_kind", "explicit_managed"),
        "status": "trace_verified" if not issues else "trace_incomplete",
        "issues": sorted(set(issues)),
        "stages": stages,
        "observed_stage_count": sum(bool(v) for v in by_stage.values()),
        "all_eight_stages_observed": all(by_stage.values())
        and all(edge["linked"] for edge in chain),
        "finish_status": finish["status"] if finish else "unknown",
        "product_qualified": False,
    }


def assess_journal(root: Path) -> dict:
    root = root.resolve()
    turns = [
        assess_turn(root, path)
        for path in sorted((root / ".managed-turns" / "starts").glob("*.json"))
    ]
    return {
        "contract": "ManagedTurnTraceCoverage",
        "started_turn_count": len(turns),
        "verified_turn_count": sum(t["status"] == "trace_verified" for t in turns),
        "correlated_turn_count": sum(
            t["status"] == "trace_verified" and t["all_stages_accounted"] for t in turns
        ),
        "complete_managed_turn_count": sum(
            t["status"] == "trace_verified"
            and t["all_eight_stages_observed"]
            and t["execution_kind"] != "standalone_profile"
            for t in turns
        ),
        "standalone_accounted_turn_count": sum(
            t["status"] == "trace_verified"
            and t["all_stages_accounted"]
            and t["standalone_profile_scope_verified"]
            for t in turns
        ),
        "failed_accounted_turn_count": sum(
            t["status"] == "trace_verified"
            and t["all_stages_accounted"]
            and t["finish_status"] == "failed"
            for t in turns
        ),
        "complete_eight_stage_turn_count": sum(
            t["status"] == "trace_verified" and t["all_eight_stages_observed"]
            for t in turns
        ),
        "turns": turns,
        "denominator_source": "durable start markers, including missing finish",
        "product_qualified": False,
        "release_authorized": False,
    }
