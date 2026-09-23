#!/usr/bin/env python3
"""Regression self-test низкоуровневых Markdown/YAML document contracts."""
from __future__ import annotations

from document_contract import markdown_headings, parse_sections, render_document, split_frontmatter
from harness_config import parse_yaml_subset


def main() -> int:
    # ``##`` внутри fenced examples остаётся содержимым текущей section и не
    # создаёт machine-readable boundary/duplicate.
    body = """# Demo

## Implementation plan

1. До fence.

```bash
## Evidence
echo demo
```

2. После fence.

~~~text
## Hidden
still code
~~~

## Evidence

real evidence
"""
    sections, duplicates = parse_sections(body)
    assert not duplicates, duplicates
    assert set(sections) == {"Implementation plan", "Evidence"}, sections
    assert "## Evidence" in sections["Implementation plan"]
    assert "2. После fence." in sections["Implementation plan"]
    assert "## Hidden" in sections["Implementation plan"]
    assert sections["Evidence"] == "real evidence"

    headings = markdown_headings(body)
    titles = [(level, title) for _index, level, title in headings]
    assert titles == [
        (1, "Demo"),
        (2, "Implementation plan"),
        (2, "Evidence"),
    ], titles

    # Serializer обязан сохранять тип каждого scalar при повторном parse.
    frontmatter = {
        "schema": 1,
        "numeric_string": "1",
        "leading_zero": "001",
        "negative_string": "-1",
        "true_string": "true",
        "false_string": "false",
        "null_string": "null",
        "language": "C#",
        "architecture_ref": "docs/architecture.md#auth",
        "quoted": "a\\\"b",
        "backslash": "a\\\\b",
        "empty": "",
        "values": ["1", "001", "true", "null", "C#", 1, True, None],
        "nested": {"phase": "1"},
    }
    rendered = render_document(frontmatter, "# Round trip")
    parsed, parsed_body = split_frontmatter(rendered)
    assert parsed == frontmatter, (parsed, frontmatter, rendered)
    assert "# Round trip" in parsed_body

    # ``#`` начинает YAML comment только после separation whitespace.
    values = parse_yaml_subset(
        """language: C#
architecture: docs/architecture.md#auth
description: C# language
commented: value # trailing comment
quoted: "C# language" # trailing comment
list:
  - C#
  - docs/architecture.md#auth
"""
    )
    assert values["language"] == "C#", values
    assert values["architecture"] == "docs/architecture.md#auth", values
    assert values["description"] == "C# language", values
    assert values["commented"] == "value", values
    assert values["quoted"] == "C# language", values
    assert values["list"] == ["C#", "docs/architecture.md#auth"], values

    print("DOCUMENT CONTRACT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
