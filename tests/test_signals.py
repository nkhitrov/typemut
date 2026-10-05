"""Tests for the SIGTERM handlers of typemut processes."""

from __future__ import annotations

import signal
import threading

from typemut.signals import TerminateSignal


def test_sigterm_interrupts_in_block() -> None:
    before = signal.getsignal(signal.SIGTERM)
    with TerminateSignal().interrupts():
        inside = signal.getsignal(signal.SIGTERM)
    assert inside is signal.default_int_handler
    assert signal.getsignal(signal.SIGTERM) == before


def test_sigterm_ends_process() -> None:
    terminate_signal = TerminateSignal()
    with terminate_signal.interrupts():
        terminate_signal.ends_process()
        inside = signal.getsignal(signal.SIGTERM)
    assert inside == signal.SIG_DFL


def test_sigterm_unchanged_outside_main_thread() -> None:
    handlers: list[object] = []

    def guarded() -> None:
        with TerminateSignal().interrupts():
            handlers.append(signal.getsignal(signal.SIGTERM))

    before = signal.getsignal(signal.SIGTERM)
    thread = threading.Thread(target=guarded)
    thread.start()
    thread.join()
    assert handlers == [before]
