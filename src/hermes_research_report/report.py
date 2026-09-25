"""Backward-compatible deterministic assembly of an evidence-linked draft."""

from __future__ import annotations

import hashlib
import html
import re
from copy import deepcopy
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit


class ReportInputError(ValueError):
    """Stable validation error retained for the public compatibility contract."""

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{path}: {message}")


def _string(maximum: int) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def _array(items: dict[str, Any], maximum: int) -> dict[str, Any]:
    return {"type": "array", "items": items, "maxItems": maximum}


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_ID = {
    **_string(64),
    "pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
}
_LIMITATIONS = _array(_string(2000), 20)
_ANALYSIS = _object(
    {
        "subquestions": _array(
            _object(
                {
                    "id": _ID,
                    "text": _string(2000),
                    "status": {
                        "type": "string",
                        "enum": ["answered", "partial", "open"],
                    },
                    "claim_ids": _array(_ID, 40),
                    "gaps": _LIMITATIONS,
                },
                ["id", "text", "status", "claim_ids", "gaps"],
            ),
            12,
        ),
        "challenges": _array(
            _object(
                {
                    "id": _ID,
                    "claim_id": _ID,
                    "alternative": _string(3000),
                    "supporting_claim_ids": _array(_ID, 40),
                    "contradicting_claim_ids": _array(_ID, 40),
                    "discriminator": _string(2000),
                    "verdict": {
                        "type": "string",
                        "enum": [
                            "plausible",
                            "weakened",
                            "rejected",
                            "unresolved",
                        ],
                    },
                    "rationale": _string(3000),
                    "gaps": _LIMITATIONS,
                },
                [
                    "id",
                    "claim_id",
                    "alternative",
                    "supporting_claim_ids",
                    "contradicting_claim_ids",
                    "discriminator",
                    "verdict",
                    "rationale",
                    "gaps",
                ],
            ),
            12,
        ),
        "synthesis": _object(
            {
                "answer": _string(5000),
                "claim_ids": _array(_ID, 40),
                "limitations": _LIMITATIONS,
                "reconsider_if": _LIMITATIONS,
            },
            ["answer", "claim_ids", "limitations", "reconsider_if"],
        ),
    },
    ["subquestions", "challenges", "synthesis"],
)
_STOP_REASONS = {
    "answer_complete": "Хост заявил завершение ответа; достаточность автоматически не удостоверена.",
    "checkpoint": "Промежуточный результат; исследование не завершено.",
    "budget_exhausted": "Исчерпан бюджет; сохранен доступный частичный результат.",
    "insufficient_evidence": "Недостаточно доказательств для полного ответа.",
    "access_blocked": "Доступ к необходимым материалам ограничен.",
}
REPORT_REQUEST_SCHEMA = _object(
    {
        "question": _string(4000),
        "response_format": {"type": "string", "enum": ["full", "structured"]},
        "stop_reason": {"type": "string", "enum": list(_STOP_REASONS)},
        "sources": _array(
            _object(
                {
                    "id": _ID,
                    "url": {**_string(2048), "pattern": r"^https?://"},
                    "title": _string(1000),
                    "text": _string(50000),
                    "family": _string(300),
                    "accessed_at": {**_string(64), "format": "date-time"},
                },
                ["id", "url", "title", "text", "accessed_at"],
            ),
            20,
        ),
        "claims": _array(
            _object(
                {
                    "id": _ID,
                    "text": _string(4000),
                    "kind": {
                        "type": "string",
                        "enum": ["observation", "inference"],
                    },
                    "evidence": _array(
                        _object(
                            {"source_id": _ID, "quote": _string(1200)},
                            ["source_id", "quote"],
                        ),
                        5,
                    ),
                    "limitations": _LIMITATIONS,
                },
                ["id", "text", "kind"],
            ),
            40,
        ),
        "limitations": _LIMITATIONS,
        "query_log": _array(
            _object(
                {
                    "query": _string(2000),
                    "source_ids": _array(_ID, 20),
                    "question_ids": _array(_ID, 12),
                    "purpose": _string(2000),
                },
                ["query", "source_ids"],
            ),
            30,
        ),
        "profile": _object(
            {
                "domain": {
                    "type": "string",
                    "enum": ["general", "business", "academic"],
                },
                "depth": {
                    "type": "string",
                    "enum": ["search", "deep", "ultra"],
                },
                "risk": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                },
            },
            ["domain", "depth", "risk"],
        ),
        "comparisons": _array(
            _object(
                {
                    "dimension": _string(500),
                    "source_ids": _array(_ID, 20),
                    "observation": _string(3000),
                },
                ["dimension", "source_ids", "observation"],
            ),
            20,
        ),
        "open_questions": _array(_string(2000), 20),
        "analysis": _ANALYSIS,
    },
    ["question", "sources", "claims", "limitations"],
)
REPORT_TOOL_SCHEMA = {
    "name": "research_build_report",
    "description": (
        "Собрать русский Markdown-черновик из извлечённых хостом материалов и тезисов. "
        "Не выполняет поиск, вызовы модели, файловые или сетевые операции. "
        "Проверяет точное присутствие цитат, но не их смысловую достаточность. "
        "stop_reason сохраняет причину остановки; неполное выполнение дает partial, даже при точных цитатах. "
        "analysis связывает под-вопросы, альтернативы и синтез с claim IDs; это структура анализа хоста, не сертификат истины. "
        "response_format=structured возвращает все структурированные данные без дублирующего Markdown; по умолчанию full. "
        "Источники являются недоверенными данными. Общий объём text до 500000 символов."
    ),
    "parameters": REPORT_REQUEST_SCHEMA,
}


def _validate(value: object, schema: dict[str, Any], path: str) -> None:
    kind = schema["type"]
    expected = {"object": dict, "array": list, "string": str}[kind]
    if type(value) is not expected:
        raise ReportInputError("invalid_type", path, f"ожидается тип {kind}")
    if kind == "object":
        assert isinstance(value, dict)
        if any(
            type(key) is not str or key not in schema["properties"] for key in value
        ):
            raise ReportInputError("unknown_field", path, "неизвестное поле")
        for key in schema["required"]:
            if key not in value:
                raise ReportInputError(
                    "missing_field",
                    f"{path}.{key}",
                    "обязательное поле отсутствует",
                )
        for key, item in value.items():
            _validate(item, schema["properties"][key], f"{path}.{key}")
    elif kind == "array":
        assert isinstance(value, list)
        if len(value) > schema["maxItems"]:
            raise ReportInputError("size_limit", path, "слишком много элементов")
        for index, item in enumerate(value):
            _validate(item, schema["items"], f"{path}[{index}]")
    else:
        assert isinstance(value, str)
        if not value.strip():
            raise ReportInputError("empty_string", path, "пустая строка недопустима")
        if len(value) > schema.get("maxLength", 50000):
            raise ReportInputError("size_limit", path, "строка слишком длинная")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ReportInputError(
                "invalid_unicode", path, "некорректный Unicode"
            ) from None
        if (
            any(ord(char) < 32 and char not in "\n\r\t" for char in value)
            or "\x7f" in value
        ):
            raise ReportInputError(
                "invalid_control", path, "недопустимый управляющий символ"
            )
        if "enum" in schema and value not in schema["enum"]:
            raise ReportInputError(
                "invalid_value", path, "значение не входит в допустимый набор"
            )
        if "pattern" in schema:
            matched = (
                re.fullmatch(schema["pattern"], value)
                if schema is _ID
                else re.search(schema["pattern"], value)
            )
            if not matched:
                raise ReportInputError("invalid_format", path, "неверный формат")


def _source_checks(source: dict[str, Any], path: str) -> None:
    url = source["url"]
    try:
        parts = urlsplit(url)
        if (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or any(char.isspace() or char in '<>\\"' or ord(char) < 32 for char in url)
        ):
            raise ValueError
        _ = parts.port
    except ValueError:
        raise ReportInputError(
            "invalid_url",
            path + ".url",
            "нужен HTTP(S) URL без реквизитов доступа",
        ) from None
    try:
        timestamp = datetime.fromisoformat(source["accessed_at"])
        if timestamp.tzinfo is None or "T" not in source["accessed_at"]:
            raise ValueError
    except ValueError:
        raise ReportInputError(
            "invalid_timestamp",
            path + ".accessed_at",
            "нужны дата и время ISO 8601 с часовым поясом",
        ) from None


def _md(value: str) -> str:
    escaped = html.escape(value, quote=False)
    escaped = re.sub(r"([\\`*{}\[\]()#+.!_|>~\-])", r"\\\1", escaped)
    return escaped.replace("\r\n", "\n").replace("\r", "\n")


def _inline(value: str) -> str:
    return _md(value).replace("\n", " ").replace("\t", " ")


def _analysis_state(
    analysis: dict[str, Any],
    claims: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    by_claim = {claim["id"]: claim for claim in claims}
    missing: list[str] = []

    def references(ids: list[str], path: str) -> bool:
        seen: set[str] = set()
        for index, claim_id in enumerate(ids):
            if claim_id not in by_claim:
                raise ReportInputError(
                    "unknown_claim_id", f"{path}[{index}]", "тезис отсутствует"
                )
            if claim_id in seen:
                raise ReportInputError(
                    "duplicate_reference", f"{path}[{index}]", "повтор ссылки"
                )
            seen.add(claim_id)
        return bool(ids) and all(by_claim[claim_id]["evidence"] for claim_id in ids)

    for group in ("subquestions", "challenges"):
        seen: set[str] = set()
        for index, item in enumerate(analysis[group]):
            if item["id"] in seen:
                raise ReportInputError(
                    "duplicate_analysis_id",
                    f"request.analysis.{group}[{index}].id",
                    "повтор идентификатора",
                )
            seen.add(item["id"])
    linked_questions = 0
    for index, question in enumerate(analysis["subquestions"]):
        linked = references(
            question["claim_ids"],
            f"request.analysis.subquestions[{index}].claim_ids",
        )
        linked_questions += bool(linked)
        if question["status"] != "answered":
            missing.append("open_subquestions")
        elif not linked:
            missing.append("subquestion_evidence_missing")
    if not analysis["subquestions"]:
        missing.append("coverage_assessment")
    for index, challenge in enumerate(analysis["challenges"]):
        path = f"request.analysis.challenges[{index}]"
        target = references([challenge["claim_id"]], path + ".claim_id")
        support = references(
            challenge["supporting_claim_ids"], path + ".supporting_claim_ids"
        )
        against = references(
            challenge["contradicting_claim_ids"], path + ".contradicting_claim_ids"
        )
        required = support if challenge["verdict"] == "plausible" else against
        if not target or (challenge["verdict"] != "unresolved" and not required):
            missing.append("challenge_evidence_missing")
    if not references(
        analysis["synthesis"]["claim_ids"], "request.analysis.synthesis.claim_ids"
    ):
        missing.append("synthesis_evidence_missing")
    coverage = {
        "basis": "host_declared_statuses_and_structural_links_not_semantic_coverage",
        "total_subquestions": len(analysis["subquestions"]),
        "answered_subquestions": sum(
            question["status"] == "answered" for question in analysis["subquestions"]
        ),
        "partial_subquestions": sum(
            question["status"] == "partial" for question in analysis["subquestions"]
        ),
        "open_subquestions": sum(
            question["status"] == "open" for question in analysis["subquestions"]
        ),
        "trace_linked_subquestions": linked_questions,
        "total_challenges": len(analysis["challenges"]),
        "challenged_claims": len(
            {challenge["claim_id"] for challenge in analysis["challenges"]}
        ),
        "declared_source_families": sorted(
            {source["family"] for source in sources if "family" in source}
        ),
        "source_independence_verified": False,
    }
    return (
        {
            "content": deepcopy(analysis),
            "coverage": coverage,
            "semantic_support_unverified": True,
        },
        list(dict.fromkeys(missing)),
    )


def build_report(request: object) -> dict[str, Any]:
    """Return a draft or partial result without search, persistence, or release."""
    _validate(request, REPORT_REQUEST_SCHEMA, "request")
    assert isinstance(request, dict)
    if sum(len(source["text"]) for source in request["sources"]) > 500000:
        raise ReportInputError(
            "size_limit",
            "request.sources",
            "общий объём text превышает 500000 символов",
        )
    source_map: dict[str, dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []
    for index, source in enumerate(request["sources"]):
        path = f"request.sources[{index}]"
        if source["id"] in source_map:
            raise ReportInputError(
                "duplicate_source_id", path + ".id", "повтор идентификатора источника"
            )
        _source_checks(source, path)
        entry = {key: source[key] for key in ("id", "url", "title", "accessed_at")}
        if "family" in source:
            entry["family"] = source["family"]
        entry.update(
            number=index + 1,
            extraction_hash=hashlib.sha256(source["text"].encode("utf-8")).hexdigest(),
            content_basis="host_extracted_text",
            coverage="not_supplied",
            origin_verified=False,
        )
        sources.append(entry)
        source_map[source["id"]] = source

    def require_source(source_id: str, path: str) -> None:
        if source_id not in source_map:
            raise ReportInputError(
                "unknown_source_id",
                path,
                "источник с таким идентификатором отсутствует",
            )

    claims: list[dict[str, Any]] = []
    claim_ids: set[str] = set()
    linked_sources: set[str] = set()
    for index, claim in enumerate(request["claims"]):
        path = f"request.claims[{index}]"
        if claim["id"] in claim_ids:
            raise ReportInputError(
                "duplicate_claim_id", path + ".id", "повтор идентификатора тезиса"
            )
        claim_ids.add(claim["id"])
        evidence = deepcopy(claim.get("evidence", []))
        for evidence_index, item in enumerate(evidence):
            evidence_path = f"{path}.evidence[{evidence_index}]"
            require_source(item["source_id"], evidence_path + ".source_id")
            if item["quote"] not in source_map[item["source_id"]]["text"]:
                raise ReportInputError(
                    "quote_mismatch",
                    evidence_path + ".quote",
                    "цитата не найдена дословно в переданном text",
                )
            item["exact_quote_match"] = True
            linked_sources.add(item["source_id"])
        claims.append(
            {
                "id": claim["id"],
                "text": claim["text"],
                "kind": claim["kind"],
                "evidence": evidence,
                "limitations": deepcopy(claim.get("limitations", [])),
                "evidence_status": "linked" if evidence else "unsupported",
                "independent_inference": claim["kind"] == "inference",
                "semantic_support_unverified": True,
            }
        )
    for group in ("query_log", "comparisons"):
        for index, item in enumerate(request.get(group, [])):
            for source_index, source_id in enumerate(item["source_ids"]):
                require_source(
                    source_id,
                    f"request.{group}[{index}].source_ids[{source_index}]",
                )

    profile = deepcopy(
        request.get("profile", {"domain": "general", "depth": "search", "risk": "low"})
    )
    missing_work: list[str] = []
    analysis_result: dict[str, Any] | None = None
    if "analysis" in request:
        analysis_result, analysis_missing = _analysis_state(
            request["analysis"], claims, sources
        )
        missing_work.extend(analysis_missing)
    question_ids = {
        question["id"]
        for question in request.get("analysis", {}).get("subquestions", [])
    }
    for index, query in enumerate(request.get("query_log", [])):
        for question_index, question_id in enumerate(query.get("question_ids", [])):
            if question_id not in question_ids:
                raise ReportInputError(
                    "unknown_question_id",
                    f"request.query_log[{index}].question_ids[{question_index}]",
                    "под-вопрос отсутствует",
                )
    stop_reason = request.get("stop_reason", "not_declared")
    if stop_reason not in ("not_declared", "answer_complete"):
        missing_work.append(stop_reason)
    linked = sum(bool(claim["evidence"]) for claim in claims)
    if linked < len(claims):
        missing_work.append("unsupported_claims")
    if not claims:
        missing_work.append("claims_missing")
    if profile["depth"] in ("deep", "ultra"):
        if analysis_result is None:
            missing_work.extend(
                ["comparative_analysis", "challenge_analysis", "coverage_assessment"]
            )
        else:
            if not any(row["source_ids"] for row in request.get("comparisons", [])):
                missing_work.append("comparative_analysis")
            if not request["analysis"]["challenges"]:
                missing_work.append("challenge_analysis")
        if profile["depth"] == "ultra":
            missing_work.append("robustness_review")
    if profile["risk"] == "high":
        missing_work.append("independent_substantive_review")
    limitations = deepcopy(request["limitations"]) + [
        "Материалы переданы хостом как недоверенные данные. Модуль не посещал URL и не проверял происхождение.",
        "extraction_hash: SHA-256 точного text в UTF-8, не доказательство исходных веб-байтов или полноты страницы.",
        "semantic_support_unverified: присутствие цитаты не доказывает тезис, причинность или корректность интерпретации.",
        "Сопоставления и журнал запросов переданы хостом; их содержание и полнота модулем не проверены.",
        "Это черновик без автоматического окончательного выпуска.",
    ]
    if profile["depth"] != "search":
        limitations.append(
            "Для запрошенного deep/ultra не подтверждены сравнительный анализ, проверка альтернатив и полнота охвата; профиль не понижен до search."
            if analysis_result is None
            else "Под-вопросы, альтернативы и синтез переданы хостом и связаны структурно; их смысл и полнота не удостоверены сборщиком."
        )
    if profile["risk"] == "high":
        limitations.append(
            "Высокий риск: требуется независимая содержательная проверка; модуль её не выполнял."
        )
    result: dict[str, Any] = {
        "status": "partial" if missing_work else "draft",
        "question": request["question"],
        "stop_reason": stop_reason,
        "profile": profile,
        "release_authorized": False,
        "semantic_support_unverified": True,
        "counts": {
            "total_claims": len(claims),
            "linked_claims": linked,
            "unlinked_claims": len(claims) - linked,
            "unique_linked_sources": len(linked_sources),
        },
        "evidence_index": {"sources": sources, "claims": claims},
        "limitations": limitations,
        "missing_work": list(dict.fromkeys(missing_work)),
        "analysis_limitations": deepcopy(request["limitations"]),
        "query_log": deepcopy(request.get("query_log", [])),
        "comparisons": deepcopy(request.get("comparisons", [])),
        "open_questions": deepcopy(request.get("open_questions", [])),
    }
    if analysis_result is not None:
        result["analysis"] = analysis_result
    if request.get("response_format", "full") == "structured":
        result["response_format"] = "structured"
    else:
        result["markdown"] = _render(result)
    return result


def classify_report_uncertainties(limitations: list[str]) -> dict[str, Any]:
    """Expose missing type labels; labels do not certify semantic correctness."""
    types = {
        "источниковая",
        "методическая",
        "прокси",
        "временная",
        "географическая",
        "сегментная",
        "причинная",
        "практическая",
    }
    rows = []
    for text in limitations:
        prefix = text.split(":", 1)[0].strip().casefold()
        rows.append({"text": text, "type": prefix if prefix in types else None})
    return {
        "status": "typed"
        if all(row["type"] for row in rows)
        else "classification_incomplete",
        "uncertainties": rows,
        "semantic_classification_verified": False,
    }


def _render(result: dict[str, Any]) -> str:
    sources = {source["id"]: source for source in result["evidence_index"]["sources"]}

    def link(source_id: str) -> str:
        source = sources[source_id]
        return f"[{source['number']}](<{source['url']}>)"

    lines = [
        "# Исследовательский черновик",
        "",
        "## Вопрос",
        "",
        _md(result["question"]),
        "",
        "Частичный результат; ограничения указаны ниже."
        if result["status"] == "partial"
        else "Рабочая версия.",
        "",
        "## Выводы",
        "",
    ]
    if result["stop_reason"] != "not_declared":
        lines.extend([_STOP_REASONS[result["stop_reason"]], ""])
    claims = result["evidence_index"]["claims"]
    fragments = sum(len(claim["evidence"]) for claim in claims)
    if not claims:
        lines.append("Тезисы не переданы; содержательный ответ отсутствует.")
    for index, claim in enumerate(claims, 1):
        refs = " ".join(
            link(source_id)
            for source_id in dict.fromkeys(
                evidence["source_id"] for evidence in claim["evidence"]
            )
        )
        marker = (
            "" if refs else " **НЕ ПОДТВЕРЖДЕНО: цитата отсутствует (unsupported).**"
        )
        kind = "Наблюдение" if claim["kind"] == "observation" else "Интерпретация"
        lines.append(f"{index}. {kind}: {_inline(claim['text'])} {refs}{marker}")
    if result["comparisons"]:
        lines.extend(["", "## Сопоставления", ""])
        for row in result["comparisons"]:
            refs = " ".join(
                link(source_id) for source_id in dict.fromkeys(row["source_ids"])
            )
            lines.append(
                f"- {_inline(row['dimension'])}: {_inline(row['observation'])} {refs}"
                + (" (нет ссылок на источники)" if not refs else "")
            )
    if "analysis" in result:
        analysis = result["analysis"]["content"]
        claim_map = {claim["id"]: claim for claim in claims}

        def claim_refs(ids: list[str]) -> str:
            source_ids = dict.fromkeys(
                evidence["source_id"]
                for claim_id in ids
                for evidence in claim_map[claim_id]["evidence"]
            )
            ids_text = ", ".join(f"`{claim_id}`" for claim_id in ids) or "не переданы"
            return (
                "Тезисы: "
                + ids_text
                + ". "
                + " ".join(link(source_id) for source_id in source_ids)
            )

        states = {
            "answered": "ответ заявлен",
            "partial": "частичный ответ",
            "open": "открыт",
        }
        verdicts = {
            "plausible": "правдоподобно",
            "weakened": "ослаблено",
            "rejected": "отвергнуто",
            "unresolved": "не разрешено",
        }
        lines.extend(
            [
                "",
                "## Под-вопросы и пробелы",
                "",
                "Статусы заявлены хостом; наличие ссылок не удостоверяет достаточность ответа.",
            ]
        )
        for question in analysis["subquestions"]:
            lines.extend(
                [
                    "",
                    f"### {_inline(question['id'])}: {_inline(question['text'])}",
                    f"Статус: {states[question['status']]}. "
                    + claim_refs(question["claim_ids"]),
                ]
            )
            lines.extend("- Пробел: " + _inline(gap) for gap in question["gaps"])
        lines.extend(
            [
                "",
                "## Проверка альтернатив",
                "",
                "Оценки выполнены хостом, не независимым проверяющим этого сборщика.",
            ]
        )
        for challenge in analysis["challenges"]:
            lines.extend(
                [
                    "",
                    f"### {_inline(challenge['id'])}: альтернатива к тезису `{challenge['claim_id']}`",
                    _inline(challenge["alternative"]),
                    "За альтернативу. " + claim_refs(challenge["supporting_claim_ids"]),
                    "Против альтернативы. "
                    + claim_refs(challenge["contradicting_claim_ids"]),
                    "Различающий признак: " + _inline(challenge["discriminator"]),
                    "Оценка: "
                    + verdicts[challenge["verdict"]]
                    + ". "
                    + _inline(challenge["rationale"]),
                ]
            )
            lines.extend("- Пробел: " + _inline(gap) for gap in challenge["gaps"])
        synthesis = analysis["synthesis"]
        lines.extend(
            [
                "",
                "## Синтез",
                "",
                _md(synthesis["answer"]),
                claim_refs(synthesis["claim_ids"]),
            ]
        )
        lines.extend(
            "- Ограничение: " + _inline(item) for item in synthesis["limitations"]
        )
        lines.extend(
            "- Пересмотреть вывод, если: " + _inline(item)
            for item in synthesis["reconsider_if"]
        )
    lines.extend(
        [
            "",
            "## Цитаты и доказательная опора",
            "",
            "Совпадение цитат проверено; смысловая достаточность автоматически не удостоверяется."
            if fragments
            else "Подтверждённая цитатная опора для основных выводов отсутствует.",
        ]
    )
    for claim in claims:
        lines.extend(["", f"### Тезис {_inline(claim['id'])}", ""])
        if not claim["evidence"]:
            lines.append(
                "**НЕ ПОДТВЕРЖДЕНО: доказательная опора не передана (unsupported).**"
            )
        for evidence in claim["evidence"]:
            lines.extend(
                [
                    f"Источник {_inline(evidence['source_id'])}: {link(evidence['source_id'])}",
                    "",
                ]
            )
            lines.extend("> " + line for line in _md(evidence["quote"]).split("\n"))
            lines.append("")
        for limitation in claim["limitations"]:
            lines.append("- Ограничение тезиса: " + _inline(limitation))
    lines.extend(["", "## Ограничения", ""])
    lines.extend("- " + _inline(item) for item in result["analysis_limitations"])
    uncertainty_types = classify_report_uncertainties(result["analysis_limitations"])
    if uncertainty_types["status"] == "classification_incomplete":
        lines.append(
            "- Классификация неопределённости не завершена: у части ограничений не указан тип; полнота разбора не подтверждена."
        )
    if result["profile"]["depth"] != "search":
        lines.append(
            "- Полнота углублённого исследования этим сборщиком не подтверждена."
        )
    if result["profile"]["risk"] == "high":
        lines.append("- Высокий риск: требуется независимая содержательная проверка.")
    if result["missing_work"]:
        missing_labels = {
            **_STOP_REASONS,
            "unsupported_claims": "Нужна доказательная опора для неподтверждённых тезисов.",
            "claims_missing": "Не сформулированы подтверждённые ответы на вопрос.",
            "comparative_analysis": "Не завершено сопоставление источников и результатов.",
            "challenge_analysis": "Не завершена проверка содержательных альтернатив.",
            "coverage_assessment": "Не установлено, какие приоритетные вопросы покрыты доказательствами.",
            "robustness_review": "Не проверена устойчивость выводов при изменении предпосылок.",
            "independent_substantive_review": "Не выполнена независимая содержательная проверка.",
            "open_subquestions": "Остаются открытые подвопросы исследования.",
            "subquestion_evidence_missing": "Не для каждого ответа на подвопрос есть доказательная опора.",
            "challenge_evidence_missing": "Не для каждой альтернативы найдены проверяющие материалы.",
            "synthesis_evidence_missing": "Обобщающий ответ не связан с достаточной доказательной опорой.",
        }
        lines.extend(["", "## Что требуется для продолжения", ""])
        lines.extend(
            "- "
            + missing_labels.get(item, "Остаётся незавершённая обязательная проверка.")
            for item in result["missing_work"]
        )
    if result["open_questions"]:
        lines.extend(["", "## Открытые вопросы", ""])
        lines.extend("- " + _inline(item) for item in result["open_questions"])
    lines.extend(["", "## Источники", ""])
    if not sources:
        lines.append("Источники не переданы.")
    for source in sources.values():
        lines.append(
            f"- {link(source['id'])} {_inline(source['title'])}; id: `{source['id']}`; "
            f"обращение: {_inline(source['accessed_at'])}."
        )
    lines.extend(
        [
            "",
            "## Состояние результата",
            "",
            f"- Фрагменты: точное совпадение проверено для {fragments} приведённых цитат; полнота исходных материалов этим не подтверждена."
            if fragments
            else "- Фрагменты: цитаты для основных выводов не переданы.",
            "- Доказательная опора: наличие цитаты проверено; её смысловая достаточность требует отдельной оценки."
            if fragments
            else "- Доказательная опора: подтверждённая цитатная опора для основных выводов отсутствует.",
            f"- Утверждения: в основной части {len(claims)} тезисов; их наличие не означает принятия вывода.",
            "- Приёмка: окончательная содержательная приёмка этим документом не подтверждена.",
            "- Доставка: получение результата пользователем не подтверждено; квитанция доставки сюда не передана.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
