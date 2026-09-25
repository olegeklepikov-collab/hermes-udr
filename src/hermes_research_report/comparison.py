"""Backward-compatible deterministic comparison of two periods."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

_TEXT_FIELDS = ("entity", "period", "unit", "basis", "source_id", "locator")
_TEXT_PROPERTY = {"type": "string", "minLength": 1, "maxLength": 2000}
_OBSERVATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [*_TEXT_FIELDS, "value"],
    "properties": {
        **{key: _TEXT_PROPERTY for key in _TEXT_FIELDS},
        "value": {"type": ["number", "null"]},
    },
}
COMPARISON_TOOL_SCHEMA = {
    "name": "research_compare_periods",
    "description": (
        "Сравнить числовые наблюдения двух периодов по объектам. Возвращает "
        "разности, относительные изменения и ссылки на ячейки. Не оценивает причинность "
        "или статистическую значимость. Пропуски не равны нулю. basis должен включать "
        "популяцию и методику; их сопоставимость устанавливает хост."
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["observations", "before", "after"],
        "properties": {
            "observations": {
                "type": "array",
                "maxItems": 10000,
                "items": _OBSERVATION_SCHEMA,
            },
            "before": _TEXT_PROPERTY,
            "after": _TEXT_PROPERTY,
        },
    },
}


def _valid_text(value: object) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= 2000


def compare_periods(
    observations: object, before: object, after: object
) -> dict[str, Any]:
    """Calculate structural differences without search, I/O, or semantic claims."""
    if not _valid_text(before) or not _valid_text(after) or before == after:
        raise ValueError("Нужны два различных непустых периода.")
    if type(observations) is not list or len(observations) > 10000:
        raise ValueError("observations: нужен список длиной не более 10000.")

    before_text = str(before)
    after_text = str(after)
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for index, raw in enumerate(observations):
        if (
            type(raw) is not dict
            or set(raw) != {*_TEXT_FIELDS, "value"}
            or not all(_valid_text(raw.get(field)) for field in _TEXT_FIELDS)
        ):
            raise ValueError(
                f"observations[{index}]: неполное или некорректное наблюдение."
            )
        row = dict(raw)
        value = row["value"]
        try:
            valid_value = value is None or (
                type(value) in (int, float) and math.isfinite(value)
            )
        except OverflowError:
            valid_value = False
        if not valid_value:
            raise ValueError(
                f"observations[{index}].value: нужно конечное число или null."
            )
        key = str(row["entity"]), str(row["period"])
        if key in indexed:
            raise ValueError(f"Повтор наблюдения {key}.")
        indexed[key] = row

    entities = sorted(
        {entity for entity, period in indexed if period in (before_text, after_text)}
    )
    comparisons: list[dict[str, Any]] = []
    for entity in entities:
        left = indexed.get((entity, before_text))
        right = indexed.get((entity, after_text))
        item: dict[str, Any] = {
            "entity": entity,
            "before": deepcopy(left),
            "after": deepcopy(right),
            "change": None,
            "relative_change_pct": None,
            "reason": None,
        }
        if (
            left is None
            or right is None
            or left["value"] is None
            or right["value"] is None
        ):
            item.update(
                status="missing",
                reason="Нет одного из значений; ноль не подставлен.",
            )
        elif (left["unit"], left["basis"]) != (right["unit"], right["basis"]):
            item.update(
                status="not_comparable",
                reason="Разные единицы или основания сравнения.",
            )
        else:
            left_value = left["value"]
            right_value = right["value"]
            assert isinstance(left_value, (int, float))
            assert isinstance(right_value, (int, float))
            change = right_value - left_value
            percentage = change / left_value * 100 if left_value > 0 else None
            if not math.isfinite(change) or (
                percentage is not None and not math.isfinite(percentage)
            ):
                raise ValueError(f"Результат для {entity} превышает числовой диапазон.")
            item.update(
                status="compared",
                change=change,
                relative_change_pct=percentage,
            )
            if percentage is None:
                item["reason"] = (
                    "Процент не рассчитан: исходное значение неположительно."
                )
        comparisons.append(item)

    compared = sum(row["status"] == "compared" for row in comparisons)
    return {
        "status": (
            "computed" if comparisons and compared == len(comparisons) else "partial"
        ),
        "before_period": before_text,
        "after_period": after_text,
        "comparisons": comparisons,
        "counts": {
            "entities": len(comparisons),
            "compared": compared,
            "missing_or_incomparable": len(comparisons) - compared,
        },
        "limitations": [
            "Расчёт использует значения и сопоставимость, заданные хостом.",
            "Разность не доказывает причинность или статистическую значимость.",
            "Точность исходных данных не увеличивается при вычислении процентов.",
        ],
    }
