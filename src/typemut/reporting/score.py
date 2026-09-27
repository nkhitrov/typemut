"""Mutation score of a results summary."""

from __future__ import annotations

from collections.abc import Mapping

from typemut.db import MutantStatus


class MutationScore:
    """Mutation scores of a results summary (``{module: {status: count}}``)."""

    def __init__(self, summary: Mapping[str, Mapping[str, int]]) -> None:
        self._summary = summary

    def total(self) -> float | None:
        """Return the overall mutation score in percent, or None if nothing was scored.

        Only killed and survived mutants count; pending, skipped and error ones don't.
        """
        killed = sum(statuses.get(MutantStatus.KILLED, 0) for statuses in self._summary.values())
        survived = sum(
            statuses.get(MutantStatus.SURVIVED, 0) for statuses in self._summary.values()
        )
        if killed + survived == 0:
            return None
        return killed / (killed + survived) * 100
