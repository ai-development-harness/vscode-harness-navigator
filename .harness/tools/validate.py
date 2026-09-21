#!/usr/bin/env python3
"""Главный dependency-free validator целостности AI Development Harness.

Назначение
----------
Проверяет protocol/repository invariants Harness до product-specific tooling.
Validator должен работать сразу после checkout, поэтому использует только Python
stdlib и Git CLI.

Режимы
------
- manual: обычная диагностика; целостный migration-pending legacy state может
  быть warning, чтобы разрешить PROJECT RECONCILE;
- commit: строгий pre-commit gate;
- ci: строгий Harness Integrity gate.

Fail-closed contract
--------------------
Повреждённый bootstrap config, недоступный Git index или невозможность доказать
обязательный safety invariant не подменяются filesystem guessing/partial PASS.

Exit codes
----------
- 0: PASS;
- 1: deterministic validation failures;
- 2: BLOCKED/bootstrap failure.

Большинство независимых checks агрегируют ошибки, чтобы один запуск показывал
максимум drift, но malformed bootstrap/policy boundaries прекращают выполнение
раньше, потому что дальнейшим значениям уже нельзя доверять.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import sys

if sys.version_info < (3, 11):
    print("ERROR: Harness validation requires Python 3.11+ (stdlib tomllib).", file=sys.stderr)
    raise SystemExit(2)

import tomllib

from command_transitions import (
    canonical_commands,
    load_transition_table,
    render_transition_markdown,
    validate_command_text,
    validate_transition_table,
)
from command_references import DEPRECATED_COMMAND_PATTERNS, find_deprecated_commands
from harness_config import (
    ConfigError,
    get,
    language_value,
    load_manifest,
    load_update_policy,
    local_brief_path,
    max_fix_review_cycles,
    protocol_path,
    repository_path,
    resolve_repo_path,
    review_policy,
    skill_search_max_results,
    update_manifest_path,
)
from project_integrity import validate_project_integrity
from project_migration import legacy_manual_bypass_allowed, legacy_schema_pending


# Безопасно вызвать Git и вернуть (exit_code, stdout). Ошибка запуска Git превращается в код 127, а не необработанное исключение.
def run_git(root: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(["git", *args], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return 127, ""
    return proc.returncode, proc.stdout



# Определить repository root через git rev-parse; fallback нужен для ограниченных окружений, где Git metadata недоступна.
def repo_root() -> Path:
    here = Path(__file__).resolve()
    code, out = run_git(here.parent, "rev-parse", "--show-toplevel")
    if code == 0 and out.strip():
        return Path(out.strip())
    return here.parents[2]



# Прочитать TOML только stdlib tomllib. Любая syntax error должна попасть в общий validation report.
def load_toml(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)



def validate_harness_policy_schema(policy: dict, errors: list[str]) -> None:
    """Проверить exact schema .harness/harness-policy.toml.

    Unknown key блокируется специально: safety knob с опечаткой не должен
    молча отключать целый класс проверок. Также обязательны все arrays/booleans,
    которые main() использует ниже.
    """
    allowed = {
        "version",
        "required_files",
        "required_skills",
        "required_agents",
        "required_commands",
        "forbidden_tracked_globs",
        "allowed_tracked_globs",
        "format_paths",
        "documented_config_globs",
        "check_config_parameter_comments",
        "check_config_parameter_examples",
        "max_tracked_file_size_mb",
        "check_utf8",
        "check_final_newline",
        "check_trailing_whitespace",
        "check_private_key_material",
        "check_merge_markers",
    }
    unexpected = sorted(set(policy) - allowed)
    if unexpected:
        errors.append(
            "harness-policy: unsupported settings: " + ", ".join(unexpected)
        )

    if policy.get("version") != 1:
        errors.append("harness-policy: version must be 1")

    list_keys = (
        "required_files",
        "required_skills",
        "required_agents",
        "required_commands",
        "forbidden_tracked_globs",
        "allowed_tracked_globs",
        "format_paths",
        "documented_config_globs",
    )
    for key in list_keys:
        value = policy.get(key)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            errors.append(f"harness-policy: {key} must be a string array")

    bool_keys = (
        "check_config_parameter_comments",
        "check_config_parameter_examples",
        "check_utf8",
        "check_final_newline",
        "check_trailing_whitespace",
        "check_private_key_material",
        "check_merge_markers",
    )
    for key in bool_keys:
        if not isinstance(policy.get(key), bool):
            errors.append(f"harness-policy: {key} must be boolean")

    size = policy.get("max_tracked_file_size_mb")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        errors.append(
            "harness-policy: max_tracked_file_size_mb must be a positive integer"
        )


# Tracked surface берётся только из Git index. Filesystem crawl здесь опасен:
# ignored/vendor/generated файл не должен неожиданно стать частью Harness
# contract, а untracked secret не равен уже отслеживаемому repository state.
def tracked_files(root: Path) -> tuple[list[str], str | None]:
    code, out = run_git(root, "ls-files", "-z")
    if code != 0:
        return [], "Git index unavailable; tracked-file integrity checks require a Git working tree"
    return [p for p in out.split("\0") if p], None



# Проверить path против набора glob patterns из policy.
def match_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)



# Проверить принадлежность path управляемой директории без ложных prefix matches вроде docs/a vs docs/abc.
def is_under(path: str, configured: list[str]) -> bool:
    p = path.replace("\\", "/")
    for item in configured:
        item = item.rstrip("/")
        if p == item or p.startswith(item + "/"):
            return True
    return False



# Быстро отличить текстовый файл от binary по NUL-byte, чтобы не декодировать произвольные artifacts как UTF-8.
def text_file(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if b"\0" in data[:8192]:
        return False
    return True



# Разобрать только простой scalar-subset YAML frontmatter, который использует Harness. Полный YAML parser намеренно не добавляется как dependency.
def parse_markdown_frontmatter(path: Path) -> dict[str, str]:
    """Parse the simple top-level scalar subset used by Harness skill/agent frontmatter."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    result: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            result[key.strip()] = value
    return result



# Извлечь обязательные name/description core skill поверх общего frontmatter parser.
def parse_skill_frontmatter(path: Path) -> tuple[str | None, str | None]:
    fields = parse_markdown_frontmatter(path)
    return fields.get("name"), fields.get("description")



# Собрать contiguous comments непосредственно перед config parameter; validator требует документацию рядом с настройкой.
def preceding_comment_block(lines: list[str], index: int) -> list[str]:
    """Return contiguous comment lines immediately preceding a config parameter."""
    comments: list[str] = []
    i = index - 1
    while i >= 0:
        stripped = lines[i].strip()
        if not stripped:
            if comments:
                break
            i -= 1
            continue
        if stripped.startswith("#"):
            comments.append(stripped[1:].strip())
            i -= 1
            continue
        break
    comments.reverse()
    return comments



# Найти реальные YAML/TOML parameters и пропустить tables/list bodies/multiline strings, чтобы comment-policy не давала лишних false positives.
def config_parameter_lines(path: Path) -> list[tuple[int, str]]:
    """Find YAML/TOML parameter lines while skipping tables, list items and multiline TOML bodies."""
    lines = path.read_text(encoding="utf-8").splitlines()
    result: list[tuple[int, str]] = []
    in_toml_multiline = False
    suffix = path.suffix.lower()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if suffix == ".toml":
            if in_toml_multiline:
                if '"""' in stripped:
                    in_toml_multiline = False
                continue
            if stripped.startswith("["):
                continue
            m = re.match(r"^([A-Za-z0-9_.-]+)\s*=", stripped)
            if m:
                result.append((idx, m.group(1)))
                if stripped.count('"""') == 1:
                    in_toml_multiline = True
            continue
        if suffix in {".yaml", ".yml"}:
            # Ключ mapping, включая list-item mappings вида `- name:`.
            m = re.match(r"^\s*(?:-\s+)?([A-Za-z0-9_.-]+):(?:\s|$)", line)
            if m:
                result.append((idx, m.group(1)))
    return result


SEMVER_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")



# Преобразовать только строгий vMAJOR.MINOR.PATCH в tuple для deterministic сравнения release graph.
def semver_tag_tuple(tag: str) -> tuple[int, int, int] | None:
    match = SEMVER_TAG_RE.fullmatch(tag)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())



# ---------------------------------------------------------------------------
# Update graph validator.
# Проверяет не только JSON schema, но и route semantics: strict forward SemVer,
# один outgoing edge, отсутствие cycles, reachability latest и согласованность
# latest с manifest release.
# ---------------------------------------------------------------------------
def validate_update_graph(root: Path, errors: list[str]) -> None:
    try:
        policy = load_update_policy(root)
        path = update_manifest_path(root)
    except ConfigError as exc:
        errors.append(f"update-graph: {exc}")
        return
    if not path.is_file():
        errors.append(f"update-graph: missing configured update manifest {path.relative_to(root)}")
        return
    tag_pattern = get(policy, "source.tag_pattern")
    if not isinstance(tag_pattern, str):
        errors.append("harness-update source.tag_pattern must be a string")
        return
    try:
        tag_re = re.compile(tag_pattern)
    except re.error as exc:
        errors.append(f"harness-update source.tag_pattern is invalid: {exc}")
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"invalid {path.relative_to(root)}: {exc}")
        return

    label = path.relative_to(root).as_posix()
    if not isinstance(data, dict):
        errors.append(f"{label} root must be an object")
        return
    if data.get("schemaVersion") != 1:
        errors.append(f"{label} schemaVersion must be 1")

    latest = data.get("latest")
    if not isinstance(latest, str) or tag_re.fullmatch(latest) is None:
        errors.append(f"{label} latest does not match configured source.tag_pattern")
        latest = None
    elif semver_tag_tuple(latest) is None:
        errors.append(f"{label} latest must use protocol SemVer ordering vMAJOR.MINOR.PATCH")
        latest = None

    transitions = data.get("transitions")
    if not isinstance(transitions, list):
        errors.append(f"{label} transitions must be an array")
        return

    outgoing: dict[str, str] = {}
    nodes: set[str] = set()
    if latest:
        nodes.add(latest)

    for index, transition in enumerate(transitions):
        prefix = f"{label} transitions[{index}]"
        if not isinstance(transition, dict):
            errors.append(f"{prefix} must be an object")
            continue

        source = transition.get("from")
        target = transition.get("to")
        source_pattern_ok = isinstance(source, str) and tag_re.fullmatch(source) is not None
        target_pattern_ok = isinstance(target, str) and tag_re.fullmatch(target) is not None
        source_v = semver_tag_tuple(source) if source_pattern_ok else None
        target_v = semver_tag_tuple(target) if target_pattern_ok else None

        if not source_pattern_ok:
            errors.append(f"{prefix}.from does not match configured source.tag_pattern")
        elif source_v is None:
            errors.append(f"{prefix}.from must use protocol SemVer ordering")
        if not target_pattern_ok:
            errors.append(f"{prefix}.to does not match configured source.tag_pattern")
        elif target_v is None:
            errors.append(f"{prefix}.to must use protocol SemVer ordering")
        if source_v is not None and target_v is not None and target_v <= source_v:
            errors.append(f"{prefix} must move strictly forward")
        if transition.get("kind") not in {"standard", "bridge"}:
            errors.append(f"{prefix}.kind must be standard or bridge")
        if not isinstance(transition.get("reloadRequired"), bool):
            errors.append(f"{prefix}.reloadRequired must be boolean")
        if transition.get("kind") == "bridge":
            reason = transition.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"{prefix}.reason is required for bridge")

        if isinstance(source, str) and isinstance(target, str):
            if source in outgoing:
                errors.append(f"{label} ambiguous route: multiple transitions from {source}")
            else:
                outgoing[source] = target
            nodes.update({source, target})

    if latest and latest in outgoing:
        errors.append(f"{label} latest must be terminal (no outgoing transition)")

    if latest:
        for graph_start in sorted(nodes):
            current = graph_start
            seen: set[str] = set()
            while current != latest:
                if current in seen:
                    errors.append(f"{label} cycle detected from {graph_start}")
                    break
                seen.add(current)
                nxt = outgoing.get(current)
                if nxt is None:
                    errors.append(f"{label} release {graph_start} cannot reach latest {latest}")
                    break
                current = nxt

        try:
            manifest = load_manifest(root)
            manifest_release = get(manifest, "harness.release")
            if isinstance(manifest_release, str) and latest != f"v{manifest_release}":
                errors.append(
                    f"{label} latest {latest} does not match manifest harness.release v{manifest_release}"
                )
        except ConfigError as exc:
            errors.append(f"manifest: {exc}")




# ---------------------------------------------------------------------------
# Главный orchestration flow validator-а.
# Порядок намеренно идёт от bootstrap/config boundaries к project/document/Git
# checks: downstream validator нельзя запускать на config, которому уже нельзя
# доверять.
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["ci", "commit", "manual"], default="manual")
    args = parser.parse_args()

    root = repo_root()
    # Ошибки намеренно накапливаются: CI/пользователь за один запуск получает
    # полный список drift/corruption. warnings не делают repository невалидным.
    errors: list[str] = []
    warnings: list[str] = []

    # manifest — bootstrap config. Все остальные repository paths разрешаются
    # через единый harness_config layer.
    try:
        load_manifest(root)
        policy_path = repository_path(root, "harnessPolicy")
    except ConfigError as exc:
        print(f"ERROR: invalid Harness manifest/config: {exc}", file=sys.stderr)
        return 2

    if not policy_path.exists():
        print(f"ERROR: missing configured harness policy: {policy_path}", file=sys.stderr)
        return 2

    try:
        policy = load_toml(policy_path)
    except Exception as exc:
        print(f"ERROR: invalid harness policy TOML: {exc}", file=sys.stderr)
        return 2

    # Все filesystem-sensitive validation surfaces опираются только на Git index
    # и явно configured paths. Ignored/vendor/generated TOML вне tracked state
    # не должны становиться скрытой частью Harness contract.
    files, git_blocker = tracked_files(root)
    if git_blocker:
        print("HARNESS VALIDATION: BLOCKED")
        print(f"  - {git_blocker}")
        return 2

    validate_update_graph(root, errors)

    # Semantics harness-policy должны быть валидны до того, как значения policy
    # начнут использоваться в остальных проверках. Unknown/missing safety keys
    # не могут молча отключить целый класс checks. Malformed policy не
    # используется дальше даже ради накопления вторичных ошибок.
    policy_errors: list[str] = []
    validate_harness_policy_schema(policy, policy_errors)
    if policy_errors:
        print("HARNESS VALIDATION: FAIL")
        for item in policy_errors:
            print(f"  - {item}")
        return 1
    max_tracked_file_size_mb = policy["max_tracked_file_size_mb"]

    # --- Обязательные protocol artifacts ---------------------------------
    # Удаление любого required file означает, что repository больше не является
    # полноценным экземпляром Harness.
    for rel in policy.get("required_files", []):
        if not (root / rel).is_file():
            errors.append(f"required file missing: {rel}")

    # --- Active project document model ------------------------------------
    # После update manual-mode умеет диагностировать legacy active schema, но
    # mutation/commit/CI запрещены до идемпотентного PROJECT RECONCILE.
    legacy_pending = legacy_schema_pending(root)
    allow_legacy = (
        args.mode == "manual"
        and legacy_pending
        and legacy_manual_bypass_allowed(root)
    )
    if legacy_pending:
        if allow_legacy:
            warnings.append(
                "active project schema migration pending; run PROJECT RECONCILE before PLAN/IMPLEMENT/GIT COMMIT/CI"
            )
        else:
            errors.append(
                "active project schema migration required or partially migrated; "
                "run PROJECT RECONCILE before continuing"
            )
    errors.extend(
        validate_project_integrity(
            root,
            warnings=warnings,
            allow_legacy=allow_legacy,
            ci_mode=args.mode == "ci",
        )
    )

    # --- Command Transition System: структура и полный command surface ----
    # Graph — structural source of truth. Пока он невалиден, нельзя доверять
    # command docs/routing: документация могла разъехаться с parser contract.
    transition_table = None
    try:
        transition_table = load_transition_table(root)
    except Exception as exc:
        errors.append(f"invalid .harness/command-transitions.json: {exc}")

    if transition_table is not None:
        errors.extend(validate_transition_table(transition_table))
        table_commands = set(canonical_commands(transition_table))

        for command in policy.get("required_commands", []):
            if command not in table_commands:
                errors.append(
                    f"harness-policy required command '{command}' missing from command transition graph"
                )

        # Legacy detector обязан предлагать только реально существующие canonical
        # commands. Иначе после будущего rename checker сам станет источником drift.
        for spec in DEPRECATED_COMMAND_PATTERNS:
            if spec.canonical not in table_commands:
                errors.append(
                    "deprecated command mapping points to unknown canonical command: "
                    f"{spec.legacy} -> {spec.canonical}"
                )
            # Добавляем whitespace delimiter: legacy формы с free-form input
            # (например ADD STEP:) по контракту не матчятся на голом token без separator.
            if not spec.pattern.search(spec.legacy + " "):
                errors.append(
                    f"deprecated command pattern does not match its own sample: {spec.legacy}"
                )

        # Regression contract detector-а: legacy STEP command должен находиться
        # даже внутри prose, но canonical namespaced форма и chain shorthand
        # не должны давать false positive.
        detector_cases = [
            ("После анализа выполни PLAN STEP-007.", {"PLAN STEP-NNN"}),
            ("После анализа выполни STEP PLAN STEP-007.", set()),
            ("GIT CHECK > COMMIT > PUSH > PR", set()),
            ("Нужен `FIX STEP-007` перед повторным review.", {"FIX STEP-NNN"}),
        ]
        for sample, expected_legacy in detector_cases:
            actual_legacy = {spec.legacy for spec, _ in find_deprecated_commands(sample)}
            if actual_legacy != expected_legacy:
                errors.append(
                    "deprecated command detector mismatch for sample "
                    f"{sample!r}: expected {sorted(expected_legacy)}, got {sorted(actual_legacy)}"
                )

        transition_docs = [
            root / "AGENTS.md",
            root / ".harness/docs/COMMANDS.md",
            root / ".harness/docs/COMMAND_SYNTAX.md",
            root / ".harness/docs/COMMAND_TRANSITIONS.md",
        ]
        for command in sorted(table_commands):
            for p in transition_docs:
                if p.is_file() and command not in p.read_text(encoding="utf-8"):
                    errors.append(
                        f"canonical command '{command}' missing from {p.relative_to(root)}"
                    )

        transitions_doc = root / ".harness/docs/COMMAND_TRANSITIONS.md"
        if transitions_doc.is_file():
            text = transitions_doc.read_text(encoding="utf-8")
            start_marker = "<!-- COMMAND-TRANSITIONS:START -->"
            end_marker = "<!-- COMMAND-TRANSITIONS:END -->"
            if start_marker not in text or end_marker not in text:
                errors.append(
                    "COMMAND_TRANSITIONS.md missing generated transition table markers"
                )
            elif text.index(start_marker) > text.index(end_marker):
                errors.append(
                    "COMMAND_TRANSITIONS.md transition table markers are reversed"
                )
            else:
                actual = text.split(start_marker, 1)[1].split(end_marker, 1)[0].strip()
                expected = render_transition_markdown(transition_table).strip()
                if actual != expected:
                    errors.append(
                        "COMMAND_TRANSITIONS.md generated table differs from .harness/command-transitions.json"
                    )

        # Exhaustive contract test: каждая canonical command обязана парситься,
        # а каждая пара chain-enabled commands валидна тогда и только тогда,
        # когда explicit edge буквально существует в graph.
        def sample_command(domain_name: str, operation: str, spec: dict) -> str:
            value = spec["canonical"].replace("STEP-NNN", "STEP-001")
            if spec.get("target") == "release-optional":
                value += " TO v0.0.0"
            if spec.get("input") == "required":
                value += " sample"
            return value

        # Перебираем полный декартов набор chain-enabled operations. Это ловит
        # не только известные примеры вроде PR→COMMIT, но и любой будущий edge drift.
        for domain_name, domain in transition_table.get("domains", {}).items():
            commands = domain.get("commands", {})
            for operation, spec in commands.items():
                sample = sample_command(domain_name, operation, spec)
                result = validate_command_text(sample, transition_table)
                if not result.get("valid"):
                    errors.append(
                        f"command parser rejects canonical sample '{sample}': "
                        f"{result.get('code')} {result.get('message')}"
                    )

            chain_operations = [
                operation
                for operation, spec in commands.items()
                if spec.get("chainAllowed")
            ]
            explicit_edges = {
                (edge.get("from"), edge.get("to"))
                for edge in domain.get("transitions", [])
            }
            for source in chain_operations:
                for target in chain_operations:
                    left = sample_command(domain_name, source, commands[source])
                    right = sample_command(domain_name, target, commands[target])
                    result = validate_command_text(
                        f"{left} > {right}",
                        transition_table,
                    )
                    expected_valid = (source, target) in explicit_edges
                    if bool(result.get("valid")) != expected_valid:
                        errors.append(
                            "command parser/graph mismatch for "
                            f"{domain_name} {source} -> {domain_name} {target}: "
                            f"expected valid={expected_valid}, got "
                            f"{result.get('code')} {result.get('message')}"
                        )

        cross_domain_probe = validate_command_text(
            "STEP PLAN STEP-001 > GIT COMMIT",
            transition_table,
        )
        if cross_domain_probe.get("valid"):
            errors.append("command parser accepted forbidden cross-domain chain")

    # --- Обязательные core skills ------------------------------------------
    # Проверяем наличие обязательных skills и минимальный frontmatter, чтобы
    # runtime routing не ссылался на исчезнувший/безымянный playbook.
    seen_skill_names: dict[str, str] = {}
    for skill in policy.get("required_skills", []):
        p = root / ".agents" / "skills" / skill / "SKILL.md"
        if not p.is_file():
            errors.append(f"required skill missing: {skill}")
    skills_root = root / ".agents" / "skills"
    if skills_root.exists():
        for p in sorted(skills_root.glob("*/SKILL.md")):
            name, desc = parse_skill_frontmatter(p)
            rel = str(p.relative_to(root))
            if not name:
                errors.append(f"skill frontmatter missing name: {rel}")
            elif name in seen_skill_names:
                errors.append(f"duplicate skill name '{name}': {seen_skill_names[name]} and {rel}")
            else:
                seen_skill_names[name] = rel
            if not desc:
                errors.append(f"skill frontmatter missing description: {rel}")

    # --- Runtime adapters: Codex / Claude ----------------------------------
    # TOML syntax и bindings Codex/Claude проверяются как protocol contract,
    # независимо от того, какой runtime используется в текущей session.
    for rel in sorted(files):
        if not rel.lower().endswith(".toml"):
            continue
        p = root / rel
        if not p.is_file():
            continue
        try:
            load_toml(p)
        except Exception as exc:
            errors.append(f"invalid tracked TOML {rel}: {exc}")

    required_agents = policy.get("required_agents", [])

    codex_cfg_path = root / ".codex" / "config.toml"
    if codex_cfg_path.exists():
        try:
            codex_cfg = load_toml(codex_cfg_path)
            agents = codex_cfg.get("agents", {})
            for agent in required_agents:
                entry = agents.get(agent)
                if not isinstance(entry, dict):
                    errors.append(f"required Codex agent binding missing: {agent}")
                    continue
                config_file = entry.get("config_file")
                if not config_file:
                    errors.append(f"Codex agent {agent} missing config_file")
                    continue
                if not isinstance(config_file, str):
                    errors.append(f"Codex agent {agent} config_file must be a string")
                    continue
                codex_agents_root = (root / ".codex" / "agents").resolve()
                resolved = (root / ".codex" / config_file).resolve()
                try:
                    resolved.relative_to(codex_agents_root)
                except ValueError:
                    errors.append(
                        f"Codex agent {agent} config escapes .codex/agents: {config_file}"
                    )
                    continue
                if resolved.suffix != ".toml":
                    errors.append(
                        f"Codex agent {agent} config must be TOML under .codex/agents: {config_file}"
                    )
                    continue
                if not resolved.is_file():
                    errors.append(f"Codex agent {agent} config missing: {config_file}")
        except Exception as exc:
            errors.append(f"Codex config/bindings cannot be parsed or validated: {exc}")

    claude_settings_path = root / ".claude" / "settings.json"
    if claude_settings_path.exists():
        try:
            claude_settings = json.loads(claude_settings_path.read_text(encoding="utf-8"))
            if not isinstance(claude_settings.get("model"), str) or not claude_settings["model"].strip():
                errors.append("Claude settings missing non-empty model")
            effort = claude_settings.get("effortLevel")
            if effort not in {"low", "medium", "high", "xhigh", "max"}:
                errors.append("Claude settings effortLevel must be low/medium/high/xhigh/max")
            permissions = claude_settings.get("permissions", {})
            if permissions and permissions.get("defaultMode") not in {
                "default", "acceptEdits", "auto", "dontAsk", "bypassPermissions", "plan"
            }:
                errors.append("Claude settings permissions.defaultMode is invalid")
        except Exception as exc:
            errors.append(f"invalid Claude settings JSON: {exc}")

    claude_agents_root = root / ".claude" / "agents"
    seen_claude_names: dict[str, str] = {}
    if claude_agents_root.exists():
        for p in sorted(claude_agents_root.glob("*.md")):
            fields = parse_markdown_frontmatter(p)
            rel = str(p.relative_to(root))
            name = fields.get("name")
            if not name:
                errors.append(f"Claude agent frontmatter missing name: {rel}")
                continue
            if name in seen_claude_names:
                errors.append(f"duplicate Claude agent name '{name}': {seen_claude_names[name]} and {rel}")
            else:
                seen_claude_names[name] = rel
            if not fields.get("description"):
                errors.append(f"Claude agent frontmatter missing description: {rel}")
            if not fields.get("model"):
                errors.append(f"Claude agent frontmatter missing model: {rel}")
            if fields.get("effort") not in {"low", "medium", "high", "xhigh", "max"}:
                errors.append(f"Claude agent invalid effort: {rel}")
            permission_mode = fields.get("permissionMode")
            if permission_mode not in {"default", "manual", "acceptEdits", "auto", "dontAsk", "bypassPermissions", "plan"}:
                errors.append(f"Claude agent invalid permissionMode: {rel}")

    for agent in required_agents:
        claude_name = agent.replace("_", "-")
        p = claude_agents_root / f"{claude_name}.md"
        if not p.is_file():
            errors.append(f"required Claude agent missing: {claude_name}")
            continue
        fields = parse_markdown_frontmatter(p)
        if fields.get("name") != claude_name:
            errors.append(f"Claude agent name mismatch: {p.relative_to(root)}")

    claude_md = root / "CLAUDE.md"
    if claude_md.exists():
        try:
            if "@AGENTS.md" not in claude_md.read_text(encoding="utf-8"):
                errors.append("CLAUDE.md must import @AGENTS.md")
        except UnicodeDecodeError:
            errors.append("CLAUDE.md is not UTF-8")

    # --- Документированность command surface ------------------------------
    # Каждая required command должна присутствовать во всех canonical routing
    # docs, иначе пользователь и агент увидят разные версии протокола.
    command_files = [
        root / "AGENTS.md",
        root / ".harness/docs/COMMAND_SYNTAX.md",
        root / ".harness/docs/COMMAND_TRANSITIONS.md",
        root / ".harness/docs/COMMANDS.md",
        root / ".harness/docs/EXECUTION_PROTOCOL.md",
    ]
    for command in policy.get("required_commands", []):
        for p in command_files:
            if p.exists() and command not in p.read_text(encoding="utf-8"):
                errors.append(f"command '{command}' missing from {p.relative_to(root)}")

    # --- Защита от возврата legacy syntax --------------------------------
    # Старые pre-namespace invocations запрещены в Harness-owned files.
    # Pattern definitions общие с PROJECT RECONCILE checker, чтобы два механизма
    # не расходились после следующего изменения command surface.
    deprecated_scan_paths = [
        root / "AGENTS.md",
        root / ".harness/manifest.yaml",
        root / ".harness/harness-policy.toml",
        root / ".harness/harness-update.toml",
        root / ".codex/config.toml",
        root / ".harness/docs/EXECUTION_PROTOCOL.md",
    ]
    deprecated_scan_paths.extend((root / ".harness/docs").glob("*.md"))
    deprecated_scan_paths.extend((root / ".agents/skills").glob("*/SKILL.md"))
    deprecated_scan_paths.extend((root / ".codex/agents").glob("*.toml"))
    deprecated_scan_paths.extend((root / ".claude").glob("*.md"))
    deprecated_scan_paths.extend((root / ".claude/agents").glob("*.md"))

    for p in deprecated_scan_paths:
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for spec in DEPRECATED_COMMAND_PATTERNS:
            if spec.pattern.search(text):
                errors.append(
                    f"deprecated command form '{spec.legacy}' found in {p.relative_to(root)}"
                )

    # --- Generated blocks и local ignore ----------------------------------
    # Проверяем markers, которые updater/initializer имеет право менять, и
    # обязательные local files, которые Git никогда не должен отслеживать.
    agents_text = (root / "AGENTS.md").read_text(encoding="utf-8") if (root / "AGENTS.md").exists() else ""
    for start, end in [
        ("<!-- PROJECT-CONTEXT:START -->", "<!-- PROJECT-CONTEXT:END -->"),
        ("<!-- SKILL-ROUTING:START -->", "<!-- SKILL-ROUTING:END -->"),
    ]:
        if start not in agents_text or end not in agents_text or agents_text.index(start) > agents_text.index(end):
            errors.append(f"AGENTS generated markers invalid: {start} / {end}")

    try:
        configured_local_brief = local_brief_path(root).relative_to(root).as_posix()
    except (ConfigError, ValueError) as exc:
        configured_local_brief = None
        errors.append(f"local brief config: {exc}")

    # Проверяем фактическую Git ignore semantics. Это корректно учитывает
    # parent patterns, glob-эквиваленты и не принимает закомментированный текст
    # за действующее правило.
    required_ignored = [
        ("AGENTS.local.md", "AGENTS.local.md"),
        ("CLAUDE.local.md", "CLAUDE.local.md"),
        (".project/local/", ".project/local/__harness_ignore_probe__"),
        (".harness/local/", ".harness/local/__harness_ignore_probe__"),
        (".codex/local/", ".codex/local/__harness_ignore_probe__"),
        (".claude/local/", ".claude/local/__harness_ignore_probe__"),
        (".claude/settings.local.json", ".claude/settings.local.json"),
        ("__pycache__/", "__pycache__/__harness_ignore_probe__.pyc"),
        ("*.py[cod]", "__harness_ignore_probe__.pyc"),
    ]
    if configured_local_brief is not None:
        required_ignored.insert(0, (configured_local_brief, configured_local_brief))
    for label, probe in required_ignored:
        code, _ = run_git(root, "check-ignore", "-q", "--no-index", "--", probe)
        if code != 0:
            errors.append(f".gitignore must ignore {label}")

    forbidden = policy.get("forbidden_tracked_globs", [])
    allowed = policy.get("allowed_tracked_globs", [])
    if configured_local_brief is not None and configured_local_brief in files:
        errors.append(f"configured local brief must not be tracked: {configured_local_brief}")
    max_size_mb = max_tracked_file_size_mb if isinstance(max_tracked_file_size_mb, int) and not isinstance(max_tracked_file_size_mb, bool) and max_tracked_file_size_mb > 0 else 10
    max_size = max_size_mb * 1024 * 1024

    for rel in files:
        normalized = rel.replace("\\", "/")
        if match_any(normalized, forbidden) and not match_any(normalized, allowed):
            errors.append(f"forbidden tracked file: {normalized}")
        p = root / rel
        try:
            if p.is_file() and p.stat().st_size > max_size:
                errors.append(f"tracked file exceeds {max_size // (1024*1024)} MiB: {normalized}")
        except OSError:
            pass

    # --- Гигиена tracked files ---------------------------------------------
    # Ищем очевидные private keys, незавершённые merge conflicts и базовые
    # text-format проблемы только в реально tracked files.
    private_markers = [b"-----BEGIN" + suffix for suffix in (b" PRIVATE KEY-----", b" RSA PRIVATE KEY-----", b" OPENSSH PRIVATE KEY-----")]
    format_paths = policy.get("format_paths", [])
    for rel in files:
        p = root / rel
        if not p.is_file() or not text_file(p):
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if policy.get("check_private_key_material", True) and any(marker in raw for marker in private_markers):
            errors.append(f"private key material detected in tracked file: {rel}")
        if policy.get("check_merge_markers", True):
            text = raw.decode("utf-8", errors="ignore")
            if re.search(r"(?m)^(<<<<<<<|=======|>>>>>>>)", text):
                errors.append(f"merge-conflict marker detected: {rel}")
        if is_under(rel, format_paths):
            if policy.get("check_utf8", True):
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    errors.append(f"managed text is not UTF-8: {rel}")
                    continue
            else:
                text = raw.decode("utf-8", errors="replace")
            if policy.get("check_final_newline", True) and raw and not raw.endswith(b"\n"):
                errors.append(f"missing final newline: {rel}")
            if policy.get("check_trailing_whitespace", True):
                for n, line in enumerate(text.splitlines(), 1):
                    if line.rstrip(" \t") != line:
                        errors.append(f"trailing whitespace: {rel}:{n}")
                        break

    # --- Самодокументируемые config files --------------------------------
    # Каждый параметр managed YAML/TOML обязан иметь соседний комментарий и
    # пример или описание формата: пользователь должен понимать настройки без чтения Python-кода.
    if policy.get("check_config_parameter_comments", True):
        config_patterns = policy.get("documented_config_globs", [])
        require_example = policy.get("check_config_parameter_examples", True)
        for rel in sorted(files):
            candidate = root / rel
            if not candidate.is_file() or candidate.suffix.lower() not in {".toml", ".yaml", ".yml"}:
                continue
            rel = rel.replace("\\", "/")
            if not match_any(rel, config_patterns):
                continue
            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                errors.append(f"documented config is not UTF-8: {rel}")
                continue
            for idx, key in config_parameter_lines(candidate):
                comments = preceding_comment_block(lines, idx)
                if not comments:
                    errors.append(f"config parameter lacks comment: {rel}:{idx + 1} ({key})")
                    continue
                if require_example and not any(
                    marker in item
                    for item in comments
                    for marker in ("Пример:", "Формат:", "Example:", "Format:")
                ):
                    errors.append(f"config parameter comment lacks example/format: {rel}:{idx + 1} ({key})")

    # --- Manifest policies -------------------------------------------------
    # language.default — реальный fallback: specialized language keys могут
    # отсутствовать. Остальные knobs читаются тем же config layer, что runtime.
    try:
        for language_key in (
            "agentResponses", "documentation", "commitMessages", "codeComments",
            "testNames", "fixtures", "githubTemplates", "releaseNotes",
        ):
            language_value(root, language_key)
        max_fix_review_cycles(root)
        review_policy(root, "security")
        review_policy(root, "tests")
        skill_search_max_results(root)
        for repository_key in (
            "gitPolicy", "harnessPolicy", "harnessUpdatePolicy",
            "harnessValidation", "harnessCI",
        ):
            configured = repository_path(root, repository_key)
            if not configured.is_file():
                errors.append(
                    f"manifest repository.{repository_key} path missing: "
                    f"{configured.relative_to(root)}"
                )

        # Эти три значения участвуют в bootstrap до того, как произвольная
        # project configuration может быть безопасно применена. Manifest
        # документирует canonical identity, но не предоставляет relocation API.
        fixed_bootstrap_paths = {
            "protocol.file": (
                protocol_path(root),
                ".harness/docs/EXECUTION_PROTOCOL.md",
            ),
            "repository.harnessPolicy": (
                repository_path(root, "harnessPolicy"),
                ".harness/harness-policy.toml",
            ),
            "repository.harnessUpdatePolicy": (
                repository_path(root, "harnessUpdatePolicy"),
                ".harness/harness-update.toml",
            ),
            "repository.harnessValidation": (
                repository_path(root, "harnessValidation"),
                ".harness/tools/validate.py",
            ),
            "repository.harnessCI": (
                repository_path(root, "harnessCI"),
                ".github/workflows/harness-integrity.yml",
            ),
        }
        for key, (configured, expected) in fixed_bootstrap_paths.items():
            actual = configured.relative_to(root).as_posix()
            if actual != expected:
                errors.append(
                    f"manifest {key} is bootstrap-fixed and must equal {expected}, got {actual}"
                )
    except ConfigError as exc:
        errors.append(f"manifest: {exc}")

    # --- Git policy: безопасные mutation rules ----------------------------
    # Проверяем semantics, от которых зависит безопасность COMMIT/PUSH/PR/SYNC:
    # force-push, protected branches, staging и PR automation.
    try:
        git_policy_path = repository_path(root, "gitPolicy")
    except ConfigError as exc:
        errors.append(f"git-policy: {exc}")
        git_policy_path = root / ".harness" / "__invalid_git_policy__"
    if git_policy_path.exists():
        try:
            gp = load_toml(git_policy_path)

            if gp.get("version") != 1:
                errors.append("git-policy: version must be 1")
            unexpected_top = sorted(
                set(gp) - {"version", "commit", "branch", "push", "pull_request", "sync"}
            )
            if unexpected_top:
                errors.append(
                    "git-policy: unsupported top-level settings: "
                    + ", ".join(unexpected_top)
                )

            commit = gp.get("commit", {})
            if commit.get("style") != "conventional":
                errors.append("git-policy: commit.style must be conventional")
            if commit.get("stage_mode") not in {"all-safe", "tracked-only", "staged-only"}:
                errors.append("git-policy: invalid commit.stage_mode")
            subject_max_length = commit.get("subject_max_length")
            if isinstance(subject_max_length, bool) or not isinstance(subject_max_length, int) or subject_max_length <= 0:
                errors.append("git-policy: commit.subject_max_length must be a positive integer")
            for key in [
                "require_body",
                "require_harness_validation",
                "require_single_logical_change",
                "include_verification",
                "include_traceability",
                "allow_empty",
                "sign",
            ]:
                if not isinstance(commit.get(key), bool):
                    errors.append(f"git-policy: commit.{key} must be boolean")
            allowed_commit_keys = {
                "style",
                "stage_mode",
                "subject_max_length",
                "require_body",
                "require_harness_validation",
                "require_single_logical_change",
                "include_verification",
                "include_traceability",
                "allow_empty",
                "sign",
                "types",
            }
            unexpected_commit = sorted(set(commit) - allowed_commit_keys)
            if unexpected_commit:
                errors.append(
                    "git-policy: unsupported commit settings: "
                    + ", ".join(unexpected_commit)
                )
            commit_types = commit.get("types")
            if not isinstance(commit_types, dict) or not commit_types or not all(
                isinstance(key, str) and key.strip()
                and isinstance(value, str) and value.strip()
                for key, value in commit_types.items()
            ):
                errors.append("git-policy: commit.types must be a non-empty string map")

            branch = gp.get("branch", {})
            protected = branch.get("protected")
            if not isinstance(protected, list) or not protected or not all(isinstance(item, str) and item.strip() for item in protected):
                errors.append("git-policy: branch.protected must be a non-empty string array")
            if branch.get("when_on_protected") not in {"auto-create", "stay", "block"}:
                errors.append("git-policy: invalid branch.when_on_protected")
            if not isinstance(branch.get("allow_initial_commit_on_protected"), bool):
                errors.append("git-policy: branch.allow_initial_commit_on_protected must be boolean")
            value = branch.get("name_pattern")
            if not isinstance(value, str) or not value.strip():
                errors.append("git-policy: branch.name_pattern must be a non-empty string")
            name_pattern = branch.get("name_pattern")
            if isinstance(name_pattern, str) and ("{prefix}" not in name_pattern or "{slug}" not in name_pattern):
                errors.append("git-policy: branch.name_pattern must contain {prefix} and {slug}")
            slug_max_length = branch.get("slug_max_length")
            if isinstance(slug_max_length, bool) or not isinstance(slug_max_length, int) or slug_max_length <= 0:
                errors.append("git-policy: branch.slug_max_length must be a positive integer")
            prefixes = branch.get("prefixes")
            if not isinstance(prefixes, dict) or not prefixes or not all(
                isinstance(key, str) and key.strip() and isinstance(value, str) and value.strip()
                for key, value in prefixes.items()
            ):
                errors.append("git-policy: branch.prefixes must be a non-empty string map")
            elif isinstance(commit_types, dict) and set(prefixes) != set(commit_types):
                errors.append(
                    "git-policy: branch.prefixes keys must exactly match commit.types keys"
                )
            allowed_branch_keys = {
                "protected",
                "when_on_protected",
                "allow_initial_commit_on_protected",
                "name_pattern",
                "slug_max_length",
                "prefixes",
            }
            unexpected_branch = sorted(set(branch) - allowed_branch_keys)
            if unexpected_branch:
                errors.append(
                    "git-policy: unsupported branch settings: "
                    + ", ".join(unexpected_branch)
                )

            push = gp.get("push", {})
            remote = push.get("remote")
            if not isinstance(remote, str) or not remote.strip():
                errors.append("git-policy: push.remote must be a non-empty string")
            if push.get("force") != "never":
                errors.append("git-policy: push.force must be never")
            for key in [
                "set_upstream",
                "fetch_before_push",
                "push_tags",
                "allow_protected",
                "allow_initial_push_to_protected",
                "require_harness_validation",
                "require_clean_worktree",
            ]:
                if not isinstance(push.get(key), bool):
                    errors.append(f"git-policy: push.{key} must be boolean")
            allowed_push_keys = {
                "remote",
                "set_upstream",
                "fetch_before_push",
                "force",
                "push_tags",
                "allow_protected",
                "allow_initial_push_to_protected",
                "require_harness_validation",
                "require_clean_worktree",
            }
            unexpected_push = sorted(set(push) - allowed_push_keys)
            if unexpected_push:
                errors.append(
                    "git-policy: unsupported push settings: "
                    + ", ".join(unexpected_push)
                )

            pull_request = gp.get("pull_request", {})
            if pull_request.get("after_push") not in {"never", "ask", "create-if-missing"}:
                errors.append("git-policy: invalid pull_request.after_push")
            for key in ["provider", "preferred_tool", "base", "body_template"]:
                value = pull_request.get(key)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"git-policy: pull_request.{key} must be a non-empty string")
            body_template = pull_request.get("body_template")
            if isinstance(body_template, str) and body_template.strip():
                try:
                    template_path = resolve_repo_path(
                        root,
                        body_template,
                        label="git-policy pull_request.body_template",
                    )
                    if not template_path.is_file():
                        errors.append(
                            "git-policy: pull_request.body_template does not exist: "
                            + body_template
                        )
                except ConfigError as exc:
                    errors.append(f"git-policy: {exc}")
            for key in ["draft", "reuse_existing", "title_from_commit"]:
                if not isinstance(pull_request.get(key), bool):
                    errors.append(f"git-policy: pull_request.{key} must be boolean")
            allowed_pr_keys = {
                "after_push",
                "provider",
                "preferred_tool",
                "base",
                "body_template",
                "draft",
                "reuse_existing",
                "title_from_commit",
            }
            unexpected_pr = sorted(set(pull_request) - allowed_pr_keys)
            if unexpected_pr:
                errors.append(
                    "git-policy: unsupported pull_request settings: "
                    + ", ".join(unexpected_pr)
                )

            sync = gp.get("sync", {})
            fetch_remote = sync.get("fetch_remote")
            if not isinstance(fetch_remote, str) or not fetch_remote.strip():
                errors.append("git-policy: sync.fetch_remote must be a non-empty string")
            if sync.get("mode") not in {"report", "ff-only"}:
                errors.append("git-policy: invalid sync.mode")
            unexpected_sync_keys = sorted(set(sync) - {"fetch_remote", "mode"})
            if unexpected_sync_keys:
                errors.append(
                    "git-policy: unsupported sync settings: " + ", ".join(unexpected_sync_keys)
                )
            if "safety" in gp:
                errors.append("git-policy: [safety] is no longer supported; use .harness/harness-policy.toml")
        except Exception as exc:
            errors.append(
                f"git-policy: cannot parse/validate {git_policy_path.relative_to(root)}: {exc}"
            )

    # В commit-mode staged state — информационная проверка: агент ещё может
    # безопасно сформировать stage согласно git-policy.
    if args.mode == "commit":
        code, staged = run_git(root, "diff", "--cached", "--name-only")
        if code == 0 and not staged.strip():
            warnings.append("no staged files yet; COMMIT agent may stage files according to git-policy")

    if warnings:
        print("WARNINGS:")
        for item in warnings:
            print(f"  - {item}")
    # Финальный exit code — публичный contract CI/tooling:
    # 0 = PASS, 1 = deterministic validation failures, 2 = bootstrap BLOCKED.
    if errors:
        print("HARNESS VALIDATION: FAIL")
        for item in errors:
            print(f"  - {item}")
        return 1

    print(f"HARNESS VALIDATION: PASS ({len(files)} tracked files checked, mode={args.mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
