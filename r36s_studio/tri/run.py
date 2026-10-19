# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Aperçu et application d'un tri/filtre/conversion, sans Qt : fonctions
synchrones à callback de progression et annulation coopérative, qui
traduisent les exceptions en codes d'erreur. Appelées par les threads Qt
(`gui/tri_runner.py`) et par le bot Telegram (`bot/`)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from r36s_studio.doublons.move import DestinationNotWritable, InsufficientDiskSpace

from .apply import apply_plan
from .plan import SORT_JOURNAL_FILENAME, SortCancelled, SortPlan, SortRootRefused, TooManyFiles

__all__ = ["ApplyOutcome", "PlanOutcome", "run_apply", "run_plan"]


@dataclass
class PlanOutcome:
    plan: Optional[SortPlan] = None
    cancelled: bool = False
    error_code: Optional[str] = None
    error_detail: str = ""


def run_plan(
    build: Callable[..., SortPlan],
    on_progress: Optional[Callable[[int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> PlanOutcome:
    """`build(on_progress=..., should_cancel=...)` : `tri.plan.build_plan`,
    `tri.filter.build_filter_plan` ou `tri.convert.build_convert_plan`,
    arguments déjà liés."""
    try:
        plan = build(on_progress=on_progress or (lambda _count: None), should_cancel=should_cancel or (lambda: False))
    except SortCancelled:
        return PlanOutcome(cancelled=True)
    except SortRootRefused as exc:
        return PlanOutcome(error_code=f"ROOT_{exc.reason.upper()}", error_detail=str(exc))
    except TooManyFiles as exc:
        return PlanOutcome(error_code="TOO_MANY_FILES", error_detail=str(exc))
    except OSError as exc:
        return PlanOutcome(error_code="IO_ERROR", error_detail=str(exc))
    return PlanOutcome(plan=plan)


@dataclass
class ApplyOutcome:
    result: Any = None  # ApplyResult
    error_code: Optional[str] = None
    error_detail: str = ""


def run_apply(
    plan: SortPlan,
    on_progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    journal_name: str = SORT_JOURNAL_FILENAME,
    apply: Callable[..., Any] = apply_plan,
) -> ApplyOutcome:
    """`apply` : `tri.apply.apply_plan` (tri, filtre) ou
    `tri.convert.apply_conversion` -- même signature."""
    try:
        result = apply(
            plan,
            on_progress=on_progress or (lambda _done, _total: None),
            should_cancel=should_cancel or (lambda: False),
            journal_name=journal_name,
        )
    except DestinationNotWritable as exc:
        return ApplyOutcome(error_code="NOT_WRITABLE", error_detail=str(exc))
    except InsufficientDiskSpace as exc:
        return ApplyOutcome(error_code="NO_SPACE", error_detail=str(exc))
    except OSError as exc:
        return ApplyOutcome(error_code="IO_ERROR", error_detail=str(exc))
    return ApplyOutcome(result=result)
