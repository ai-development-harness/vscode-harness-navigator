#!/usr/bin/env python3
"""Тонкий публичный wrapper deterministic Git preflight.

Вся policy/schema/repository логика находится в git_preflight.py. Отдельный
hyphenated filename существует как стабильный пользовательский CLI path.
"""
from __future__ import annotations

from git_preflight import main


if __name__ == "__main__":
    raise SystemExit(main())
