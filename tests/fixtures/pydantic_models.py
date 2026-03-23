"""Fixture: Pydantic-style model annotations."""

from __future__ import annotations

from typing import Annotated, Literal


class LoanState:
    pass


class ActiveLoan(LoanState):
    pass


class ClosedLoan(LoanState):
    pass


class OverdueLoan(LoanState):
    pass


class LoanModel:
    state: ActiveLoan
    amount: int
    description: str | None
    status: Literal["active", "closed"]
    metadata: Annotated[str, "some metadata"]
