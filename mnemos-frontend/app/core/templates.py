from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape
from jinja2.utils import LRUCache


class _StringKeyedCache(LRUCache):
    def _k(self, key):
        return key[0] if isinstance(key, tuple) and len(key) == 2 and isinstance(key[0], str) else key

    def get(self, key, default=None):
        return super().get(self._k(key), default)

    def __setitem__(self, key, value):
        super().__setitem__(self._k(key), value)

    def __delitem__(self, key):
        super().__delitem__(self._k(key))

    def __contains__(self, key):
        return super().__contains__(self._k(key))

    def pop(self, key, *args):
        return super().pop(self._k(key), *args)


def _make_env(directory: str) -> Environment:
    loader = FileSystemLoader(directory)
    env = Environment(
        loader=loader,
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
        cache_size=64,
        auto_reload=False,
    )
    env.cache = _StringKeyedCache(capacity=64)
    return env


def build_templates(directory: str = "app/templates") -> Jinja2Templates:
    abs_dir = directory
    if not os.path.isabs(abs_dir):
        abs_dir = str((Path(__file__).resolve().parent.parent / directory).resolve())
    if not os.path.isdir(abs_dir):
        abs_dir = directory
    return Jinja2Templates(env=_make_env(abs_dir))


def render(
    jinja: Jinja2Templates,
    request: Any,
    name: str,
    context: Mapping[str, Any] | None = None,
    status_code: int = 200,
    headers: Mapping[str, str] | None = None,
) -> Any:
    ctx = dict(context or {})
    ctx.setdefault("request", request)
    return jinja.TemplateResponse(
        request,
        name,
        context=ctx,
        status_code=status_code,
        headers=headers,
    )
