"""What SIGTERM does to a typemut process."""

from __future__ import annotations

import signal
import threading
from collections.abc import Iterator
from contextlib import contextmanager


class TerminateSignal:
    """Installs SIGTERM handlers; the seam for this process-wide side effect."""

    @contextmanager
    def interrupts(self) -> Iterator[None]:
        """In the block SIGTERM raises KeyboardInterrupt, as Ctrl+C does.

        A CI timeout then stops a run like Ctrl+C: finished results are
        saved. The earlier handler is restored afterwards. Outside the main
        thread, where handlers cannot be installed, nothing changes.
        """
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        previous = signal.signal(signal.SIGTERM, signal.default_int_handler)
        try:
            yield
        finally:
            # None: the earlier handler was not installed from Python.
            signal.signal(signal.SIGTERM, previous or signal.SIG_DFL)

    def ends_process(self) -> None:
        """Make SIGTERM end the process, as it does by default.

        For worker processes forked while :meth:`interrupts` was in effect.
        """
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
