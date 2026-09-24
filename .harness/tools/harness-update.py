#!/usr/bin/env python3
"""Публичный CLI deterministic Harness self-update engine."""
from __future__ import annotations

import sys


if __name__ == "__main__":
    # `recover` обязан работать даже после прерванного hop, когда модули
    # `.harness/tools/**` частично принадлежат разным releases. Поэтому он
    # импортирует только stdlib-модуль журнала, а не весь update engine.
    if len(sys.argv) > 1 and sys.argv[1] == "recover":
        from update_recovery import main as recover_main

        raise SystemExit(recover_main(sys.argv[2:]))

    from harness_update import main

    raise SystemExit(main())
