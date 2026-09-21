#!/usr/bin/env python3
"""Regression self-test manifest/config boundary."""
from __future__ import annotations

from pathlib import Path
import tempfile

from harness_config import ConfigError, language_value, load_git_policy


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def manifest(default: str = "ru", documentation: str | None = None) -> str:
    specialized = (
        ""
        if documentation is None
        else f"  documentation: {documentation}\n"
    )
    return (
        "language:\n"
        f"  default: {default}\n"
        f"{specialized}"
        "repository:\n"
        "  gitPolicy: config/git-policy.toml\n"
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-config-contract-") as tmp:
        root = Path(tmp)
        write(root / ".harness/manifest.yaml", manifest())
        write(root / "config/git-policy.toml", '[push]\nremote = "publish"\n')

        assert language_value(root, "documentation") == "ru"
        assert load_git_policy(root)["push"]["remote"] == "publish"

        write(root / ".harness/manifest.yaml", manifest("pt-BR", "en-US"))
        assert language_value(root, "documentation") == "en-US"
        assert language_value(root, "fixtures") == "pt-BR"

        write(root / ".harness/manifest.yaml", manifest("toolongprimary"))
        try:
            language_value(root, "documentation")
        except ConfigError as exc:
            assert "BCP 47" in str(exc), exc
        else:
            raise AssertionError("invalid language.default was accepted")

        write(root / ".harness/manifest.yaml", manifest("ru", "not_a_tag"))
        try:
            language_value(root, "documentation")
        except ConfigError as exc:
            assert "BCP 47" in str(exc), exc
        else:
            raise AssertionError("invalid specialized language tag was accepted")

    print("HARNESS CONFIG SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
