"""OCR engines. The rest of the pipeline only relies on the OcrEngine protocol.

To change provider, write a class with the same members and register it
in ENGINES; OCR_ENGINE in .env selects it.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests
from dotenv import dotenv_values

from .pdf import RenderSpec

log = logging.getLogger(__name__)

RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class OcrError(Exception):
    """This page could not be read; other pages may still work."""


class OcrUnavailable(OcrError):
    """The service is down or refuses us; retry in a later run."""


class OcrConfigError(Exception):
    """A setting is missing or invalid."""


@dataclass(frozen=True)
class OcrResult:
    text: str
    seconds: float            # time of the successful call
    raw: dict[str, Any]       # full provider response, kept for traceability


class OcrEngine(Protocol):
    name: str

    @property
    def settings(self) -> dict[str, Any]: ...

    @property
    def render_spec(self) -> RenderSpec: ...

    def read_image(self, image: bytes) -> OcrResult: ...


class LightOnOcr:
    """LightOnOCR-3 behind an OpenAI-compatible chat completions endpoint.

    Follows the model card: one image, no text prompt (any instruction other
    than "grounding" is out of distribution), 1540 px on the longest side.
    """

    name = "lightonocr"

    def __init__(
        self,
        endpoint: str,
        key: str,
        model: str = "lightonocr-3-1b-test",
        max_side: int = 1540,
        image_format: str = "png",
        timeout: float = 180,
        attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if image_format not in ("png", "jpeg"):
            raise OcrConfigError(f"unsupported OCR image format: {image_format}")
        if max_side < 1:
            raise OcrConfigError("OCR image size must be positive")
        self._endpoint, self._key = endpoint, key
        self._timeout, self._attempts, self._sleep = timeout, attempts, sleep
        self._image_format, self._max_side, self._model = image_format, max_side, model
        self._params = {"max_tokens": 4096, "temperature": 0.2, "top_p": 0.9}

    @property
    def settings(self) -> dict[str, Any]:
        return {
            "engine": self.name, "model": self._model, "max_side": self._max_side,
            "image_format": self._image_format, **self._params,
        }

    @property
    def render_spec(self) -> RenderSpec:
        return RenderSpec(self._max_side, self._image_format)

    def read_image(self, image: bytes) -> OcrResult:
        url = f"data:image/{self._image_format};base64,{base64.b64encode(image).decode()}"
        body = {
            "model": self._model,
            "messages": [{
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": url}}],
            }],
            **self._params,
        }
        raw, seconds = self._post(body)
        try:
            choice = raw["choices"][0]
            text, finish = choice["message"]["content"], choice["finish_reason"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OcrError("unexpected response structure") from exc
        if finish != "stop":
            raise OcrError(f"incomplete transcription (finish_reason={finish})")
        if not isinstance(text, str) or not text.strip():
            raise OcrError("empty transcription")
        return OcrResult(text.strip(), seconds, raw)

    def _post(self, body: dict) -> tuple[Any, float]:
        problem = ""
        for attempt in range(1, self._attempts + 1):
            start = time.perf_counter()
            wait = 2.0 ** attempt
            try:
                response = requests.post(
                    self._endpoint, json=body, timeout=(10, self._timeout),
                    headers={"Authorization": f"Bearer {self._key}"},
                    allow_redirects=False,  # never send the key elsewhere
                )
            except requests.RequestException as exc:
                problem = self._redact(f"{type(exc).__name__}: {exc}")
            else:
                seconds = time.perf_counter() - start
                if response.status_code == 200:
                    try:
                        return response.json(), seconds
                    except ValueError as exc:
                        raise OcrError("response is not JSON") from exc
                problem = self._redact(f"HTTP {response.status_code}: {response.text[:200]}")
                if response.status_code in (401, 403, 404):
                    raise OcrUnavailable(problem)
                if response.status_code not in RETRY_STATUS:
                    raise OcrError(problem)
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    wait = max(wait, min(int(retry_after), 60))
            if attempt < self._attempts:
                log.warning("OCR attempt %d/%d: %s", attempt, self._attempts, problem)
                self._sleep(wait)
        raise OcrUnavailable(problem)

    def _redact(self, message: str) -> str:
        """Errors are logged: keep the key and the endpoint out of them."""
        message = message.replace(self._key, "***")
        message = re.sub(r"host='[^']*'", "host=***", message)
        return re.sub(r"(url: |https?://)\S+", r"\1***", message)


ENGINES = {LightOnOcr.name: LightOnOcr}


def engine_from_env(env_file: Path, **overrides: Any) -> OcrEngine:
    env = {**os.environ, **{k: v for k, v in dotenv_values(env_file).items() if v}}
    name = env.get("OCR_ENGINE", LightOnOcr.name)
    if name not in ENGINES:
        raise OcrConfigError(f"unknown OCR_ENGINE {name!r}; known: {', '.join(ENGINES)}")
    missing = [n for n in ("OCR_ENDPOINT", "OCR_KEY") if not env.get(n)]
    if missing:
        raise OcrConfigError(f"missing {', '.join(missing)} in {env_file}")
    options: dict[str, Any] = {}
    if env.get("OCR_MODEL"):
        options["model"] = env["OCR_MODEL"]
    options.update({k: v for k, v in overrides.items() if v is not None})
    return ENGINES[name](env["OCR_ENDPOINT"], env["OCR_KEY"], **options)
