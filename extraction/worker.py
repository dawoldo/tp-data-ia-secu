"""Parse PDFs in a child process, so that a hostile or broken file cannot crash,
hang or exhaust the memory of the pipeline."""

from __future__ import annotations

import multiprocessing
import os
import resource
import signal
from collections.abc import Callable
from typing import Any

from .pdf import PdfError, RenderSpec, analyse, render_page

MEMORY_LIMIT = 4 * 1024**3  # address space of the child, in bytes

_context = multiprocessing.get_context("spawn")


def _serve(connection: Any) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # the parent decides when to stop
    os.dup2(2, 1)  # stdout carries the results of the parent: never write there
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))
    while True:
        try:
            request = connection.recv()
        except EOFError:
            return
        try:
            function, arguments = request
            answer = (True, function(*arguments))
        except PdfError as exc:
            answer = (False, str(exc))
        except MemoryError:
            answer = (False, "too much memory needed")
        except Exception as exc:  # whatever the parser raises is this PDF's problem
            answer = (False, f"{type(exc).__name__}: {exc}")
        connection.send(answer)


class PdfWorker:
    def __init__(self, timeout: float = 120, max_pages: int = 100) -> None:
        self._timeout, self._max_pages = timeout, max_pages
        self._process: Any = None
        self._connection: Any = None

    def __enter__(self) -> PdfWorker:
        return self

    def __exit__(self, *_: object) -> None:
        self._stop()

    def _start(self) -> None:
        self._connection, child = _context.Pipe()
        self._process = _context.Process(target=_serve, args=(child,), daemon=True)
        self._process.start()
        child.close()

    def _stop(self) -> None:
        if self._process is not None:
            self._process.kill()
            self._process.join()
            self._connection.close()
            self._process = None

    def analyse(
        self, data: bytes, spec: RenderSpec | None = None, with_text: bool = True
    ) -> dict[str, Any]:
        return self._call(analyse, data, spec, with_text, self._max_pages)

    def render_page(self, data: bytes, spec: RenderSpec, number: int) -> bytes:
        return self._call(render_page, data, spec, number)

    def _call(self, function: Callable[..., Any], *arguments: Any) -> Any:
        if self._process is None or not self._process.is_alive():
            self._stop()
            self._start()
        try:
            self._connection.send((function, arguments))
            if not self._connection.poll(self._timeout):
                self._stop()
                raise PdfError(f"parsing took more than {self._timeout:g} s")
            ok, answer = self._connection.recv()
        except (EOFError, OSError) as exc:
            self._stop()
            raise PdfError("the PDF parser crashed") from exc
        if not ok:
            raise PdfError(answer)
        return answer
