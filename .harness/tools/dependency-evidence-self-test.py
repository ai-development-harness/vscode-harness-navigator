#!/usr/bin/env python3
"""#295: transitive stale completion evidence and runtime-neutral Verify guards.

Регрессия использует реальные canonical REQ/STEP snapshots и подменяет только
исторический REVIEW storage. Это проверяет dependency freshness независимо
от git history/LLM, не создавая фиктивные «новые» завершения.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
from unittest.mock import patch

from planning_contract import (
    dependency_completion_basis,
    historical_completion_projection_proof,
    planning_context_basis,
    read_task,
    step_completion_proof,
    _validate_task,
)
from verification import verification_context_basis, verification_dependency_facts
from projection_contract import render_requirements_status


MANIFEST = """execution:
  verificationCommandTimeoutSeconds: 300
sources:
  requirements: docs/requirements
  adrDirectory: docs/adr
  openQuestions: docs/open-questions
  principles: docs/principles
  architecture: docs/architecture.md
protocol:
  taskDirectory: planning/tasks
  reviewDirectory: planning/reviews
"""


def write(root: Path, rel: str, value: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def requirement(step_id: str, req_id: str) -> str:
    return f"""---
schema: 1
id: {req_id}
source: fixture
priority: medium
steps:
  - {step_id}
adrs: []
---

# {req_id} — Completion fixture

## Requirement

Implement {step_id} with approved behavior.

## Rationale

Dependency test.

## Acceptance

- Behavior remains correct.
"""


def step(step_id: str, req_id: str, dependency: str | None = None) -> str:
    deps = "depends_on: []" if dependency is None else f"depends_on:\n  - {dependency}"
    return f"""---
schema: 1
id: {step_id}
status: completed
type: implementation
priority: medium
phase: P1
{deps}
requirements:
  - {req_id}
adrs: []
architecture_refs: []
risk_flags:
  - none
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# {step_id} — Dependency fixture

## Goal

Deliver {step_id}.

## Context

Fixture.

## Scope

- Implement.

## Mutation policy

### Allowed

- src/

### Conditional

- none

### Forbidden

- unrelated

## Out of scope

- Other work.

## Acceptance criteria

- Deliver stable behavior.

## Verification

- manual: verify feature

## Deliverables

- Implementation.

## Implementation plan

- Implementation done.

## Evidence

- Verified by independent review.

## Blocker / Failure reason

—
"""


def blocked_dag_regression() -> None:
    """#340: общий BLOCKED узел вычисляется один раз, причины не меняются."""
    import planning_contract as pc

    with tempfile.TemporaryDirectory(prefix="harness-blocked-dag-") as tmp:
        root = Path(tmp)
        basis = "sha256:" + "1" * 64
        tasks = {}
        for number in range(1, 13):
            tasks[f"STEP-{number:03d}"] = {
                "frontmatter": {
                    "id": f"STEP-{number:03d}", "status": "completed",
                    "type": "implementation",
                    "depends_on": [f"STEP-{n:03d}" for n in
                                   (number - 1, number - 2) if n > 0],
                },
                "sections": {"Evidence": "Результат проверен."},
            }

        def trusted(_root, step_id, **_kwargs):
            return {
                "path": root / f"{step_id}.md", "verdict": "PASS",
                "content_hash": "sha256:" + "2" * 64,
                "document": {"frontmatter": {"contract_basis": basis}},
            }

        # Exact опубликованный proof из issue: ускорение не переписывает
        # исторический BLOCKED в PASS и не изменяет его fingerprint.
        with patch("planning_contract.read_task", side_effect=lambda _r, s: tasks[s]) as reads, \
             patch("planning_contract.planning_context_basis", return_value=basis), \
             patch("review_contract.latest_trusted_review", side_effect=trusted):
            proof = pc.step_completion_proof(root, "STEP-012")
            assert not proof["complete"], proof
            assert proof["proof_hash"] == (
                "sha256:e0a572e8a4525b55219f45a5c4d95483981dce374dab3d90e979aaf43f5bbe7e"
            ), proof
            assert reads.call_count == 12, reads.call_count
            assert "dependency-cycle:" not in str(proof["reasons"])

            # Циклы сохраняют контекст пути. Один кеш используется повторно
            # из разных точек входа: ответы должны совпадать с чистым обходом.
            tasks["STEP-001"]["frontmatter"]["depends_on"] = ["STEP-003"]
            cache = {}
            for step_id in ("STEP-003", "STEP-002", "STEP-001"):
                expected = pc.step_completion_proof(root, step_id)
                actual = pc.step_completion_proof(root, step_id, _proof_cache=cache)
                assert actual == expected, (actual, expected)
                assert not actual["complete"]
                assert "dependency-cycle:" in str(actual["reasons"])
                assert (step_id, None) not in cache
                before = reads.call_count
                assert pc.step_completion_proof(root, step_id, _proof_cache=cache) == actual
                assert reads.call_count == before, "same cycle context should reuse cache"

            # Даже заведомо общий кеш не должен скрывать текущий back-edge.
            cached_leaf = {("STEP-001", None): {"complete": True}}
            back_edge = pc.step_completion_proof(
                root, "STEP-001", _ancestors=frozenset({"STEP-001"}),
                _proof_cache=cached_leaf,
            )
            assert back_edge["reasons"] == ["dependency-cycle:STEP-001"]

    # Реальные canonical STEP/REQ и planning basis: отказ исторического REVIEW
    # на разветвлённом DAG остаётся тем же, чтения ограничены числом узлов.
    with tempfile.TemporaryDirectory(prefix="harness-canonical-blocked-dag-") as tmp:
        root = Path(tmp)
        write(root, ".harness/manifest.yaml", MANIFEST)
        depth = 12
        for number in range(1, depth + 1):
            step_id, req_id = f"STEP-{number:03d}", f"REQ-{number:03d}"
            text = step(step_id, req_id, f"STEP-{number - 1:03d}" if number > 1 else None)
            if number > 2:
                text = text.replace("requirements:\n", f"  - STEP-{number - 2:03d}\nrequirements:\n", 1)
            write(root, f"planning/tasks/{step_id}.md", text)
            write(root, f"docs/requirements/{req_id}-fixture.md", requirement(step_id, req_id))
            write(root, f"planning/reviews/{step_id}/REVIEW-proof.md", "Historical REVIEW.\n")
        bases = {f"STEP-{n:03d}": planning_context_basis(root, f"STEP-{n:03d}")
                 for n in range(1, depth + 1)}
        verdict = "PASS"

        def historical(_root, step_id, **_kwargs):
            return {
                "path": root / f"planning/reviews/{step_id}/REVIEW-proof.md",
                "verdict": verdict,
                "document": {"frontmatter": {"contract_basis": bases[step_id]}},
            }

        class NoReuseCache(dict):
            # Эталон без повторного использования: та же семантика, все пути.
            def get(self, key, default=None):
                return default

        with patch("review_contract.latest_trusted_review", side_effect=historical):
            expected = step_completion_proof(root, "STEP-012", _proof_cache=NoReuseCache())
            with patch("planning_contract.read_task", wraps=pc.read_task) as reads:
                actual = step_completion_proof(root, "STEP-012")
            assert actual == expected
            assert not actual["complete"]
            assert reads.call_count <= depth * 6, reads.call_count
            print(f"BLOCKED DAG: {depth} nodes, {reads.call_count} canonical task reads")

            # Stale contract и FAIL REVIEW остаются отказами даже при общем кеше.
            bases["STEP-001"] = "sha256:" + "0" * 64
            stale = step_completion_proof(root, "STEP-012")
            assert not stale["complete"]
            assert "completion-contract-stale:STEP-001" in str(stale["reasons"])
            verdict = "FAIL"
            failed = step_completion_proof(root, "STEP-012")
            assert not failed["complete"]
            assert "latest trusted review verdict is not PASS" in str(failed["reasons"])

        with patch("review_contract.latest_trusted_review", return_value=None), \
             patch("review_contract.legacy_completed_steps", return_value={}):
            missing = step_completion_proof(root, "STEP-012")
            assert not missing["complete"]
            assert "trusted PASS review is missing" in str(missing["reasons"])


def historical_publication_regression() -> None:
    """#345/#346: одинаковая приёмка истории с basis и без него."""
    from traceability_coverage import build_coverage

    for has_basis in (False, True):
        with tempfile.TemporaryDirectory(prefix="harness-historical-publication-") as tmp:
            root = Path(tmp)
            write(root, ".harness/manifest.yaml", MANIFEST)
            write(root, "docs/architecture.md", "## Module map\n\nАдаптер провайдера.\n")
            for number in (1, 2):
                sid, rid = f"STEP-{number:03d}", f"REQ-{number:03d}"
                text = step(sid, rid, "STEP-001" if number == 2 else None)
                if number == 1:
                    text = text.replace("architecture_refs: []", "architecture_refs:\n  - docs/architecture.md#module-map")
                write(root, f"planning/tasks/{sid}.md", text)
                write(root, f"docs/requirements/{rid}-fixture.md", requirement(sid, rid))
                write(root, f"planning/reviews/{sid}/REVIEW-proof.md", "Исторический PASS.\n")
            stored = {sid: planning_context_basis(root, sid) for sid in ("STEP-001", "STEP-002")}
            before = {path: path.read_bytes() for path in root.rglob("*.md")}
            verdict = "PASS"

            def trusted(_root, sid, **_kwargs):
                return {"path": root / f"planning/reviews/{sid}/REVIEW-proof.md",
                        "verdict": verdict, "document": {"frontmatter":
                            {"contract_basis": stored[sid]} if has_basis else {}}}

            with patch("review_contract.latest_trusted_review", side_effect=trusted):
                for changed in (False, True):
                    if changed:
                        write(root, "docs/architecture.md", "## Module map\n\nУточнено описание принятого адаптера.\n")
                    errors = []
                    for sid in stored:
                        _validate_task(root, sid, read_task(root, sid), errors, None)
                        assert historical_completion_projection_proof(root, sid)["complete"]
                    assert not errors, errors
                    coverage = build_coverage(root)
                    assert coverage["metrics"]["verified"] == 2, coverage
                    assert coverage["metrics"]["staleEvidence"] == 0, coverage
                if has_basis:
                    # Новый consumer не может использовать историческую приёмку
                    # вместо актуального proof: strict boundary остаётся BLOCKED.
                    assert not step_completion_proof(root, "STEP-002")["complete"]
                    assert not verification_dependency_facts(root, "STEP-002")[0]["complete"]
                verdict = "FAIL"
                assert not historical_completion_projection_proof(root, "STEP-002")["complete"]
                verdict = "PASS"
                # Настоящий цикл остаётся ошибкой и исторического режима.
                path = root / "planning/tasks/STEP-001.md"
                original = path.read_text()
                path.write_text(original.replace("depends_on: []", "depends_on:\n  - STEP-002"))
                assert not historical_completion_projection_proof(root, "STEP-002")["complete"]
                path.write_text(original)
            for path, content in before.items():
                if path.name != "architecture.md":
                    assert path.read_bytes() == content, path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-dependency-enforcement-") as tmp:
        root = Path(tmp)
        write(root, ".harness/manifest.yaml", MANIFEST)
        for number in range(1, 4):
            step_id, req_id = f"STEP-{number:03d}", f"REQ-{number:03d}"
            write(root, f"docs/requirements/{req_id}-fixture.md",
                  requirement(step_id, req_id))
            write(root, f"planning/tasks/{step_id}.md",
                  step(step_id, req_id, "STEP-001" if number == 2 else None))
            write(root, f"planning/reviews/{step_id}/REVIEW-proof.md",
                  "Immutable historical evidence.\n")

        basis = {
            f"STEP-{n:03d}": planning_context_basis(root, f"STEP-{n:03d}")
            for n in range(1, 4)
        }

        # Только snapshot из настоящего REVIEW, а не изменяемый current state,
        # может подтвердить повторную проверку downstream after upstream re-plan.
        dependency_review_basis: str | None = None
        modern_review_missing_basis = False
        review_paths = {
            f"STEP-{n:03d}": root / f"planning/reviews/STEP-{n:03d}/REVIEW-proof.md"
            for n in range(1, 4)
        }

        def trusted(_root: Path, step_id: str, **_kwargs):
            meta = {"contract_basis": basis[step_id]}
            if step_id == "STEP-002" and dependency_review_basis is not None:
                meta["dependency_completion_basis"] = dependency_review_basis
            if step_id == "STEP-002" and modern_review_missing_basis:
                meta["reviewed_subject_content_hash"] = "sha256:" + "1" * 64
            return {
                "path": review_paths[step_id],
                "verdict": "PASS",
                "document": {"frontmatter": meta},
            }

        with patch("review_contract.latest_trusted_review", side_effect=trusted):
            dependency_review_basis = dependency_completion_basis(root, "STEP-002")
            assert dependency_review_basis is not None
            for number in range(1, 4):
                assert step_completion_proof(root, f"STEP-{number:03d}")["complete"]

            # Сохраняем exact historical REQ projection из старого
            # непротиворечивого contract. В обновлении он не должен дрейфовать
            # только потому, что у REVIEW отсутствуют новые metadata.
            historical_projection = render_requirements_status(root)

            # Смешанная история: REVIEW с contract_basis от более ранней
            # версии Harness ещё не содержит dependency_completion_basis.
            # Его нельзя автоматически считать актуальным для downstream.
            stored_dependency_basis = dependency_review_basis
            dependency_review_basis = None
            missing_basis = step_completion_proof(root, "STEP-002")
            assert not missing_basis["complete"], missing_basis
            assert "completion-dependency-proof-missing:STEP-002" in missing_basis["reasons"]
            assert step_completion_proof(root, "STEP-001")["complete"]

            # Canary v0.11.6 содержит завершённые STEP и immutable REVIEW без
            # dependency_completion_basis. Structural validator обязан
            # сохранять historical state как предупреждение при update, но
            # runtime-продолжение по-прежнему НЕ получает completion PASS.
            validation_errors: list[str] = []
            validation_warnings: list[str] = []
            _validate_task(
                root, "STEP-002", read_task(root, "STEP-002"),
                validation_errors, validation_warnings,
            )
            assert not any(
                "completed STEP completion proof failed" in x
                for x in validation_errors
            ), validation_errors
            assert not validation_warnings, validation_warnings
            assert not step_completion_proof(root, "STEP-002")["complete"]
            assert render_requirements_status(root) == historical_projection, (
                "updater must preserve old REQ projection without permitting runtime"
            )

            # Новый REVIEW обязан содержать dependency proof; просто убрать
            # поле при новой записи нельзя — это остаётся строгой ошибкой.
            modern_review_missing_basis = True
            modern_errors: list[str] = []
            modern_warnings: list[str] = []
            _validate_task(
                root, "STEP-002", read_task(root, "STEP-002"),
                modern_errors, modern_warnings,
            )
            assert any(
                "completed STEP completion proof failed: completion-dependency-proof-missing"
                in x for x in modern_errors
            ), modern_errors
            assert render_requirements_status(root) != historical_projection
            modern_review_missing_basis = False
            assert step_completion_proof(root, "STEP-003")["complete"]
            dependency_review_basis = stored_dependency_basis
            assert step_completion_proof(root, "STEP-002")["complete"]

            before_dependency = verification_context_basis(root, "STEP-002")
            before_unrelated = verification_context_basis(root, "STEP-003")

            # Уточнение REQ-001 не меняет STEP-001 contract напрямую.
            # Однако его REVIEW был сделан для предыдущей семантики и
            # уже не может быть current completion proof для STEP-002.
            req = root / "docs/requirements/REQ-001-fixture.md"
            old = req.read_text(encoding="utf-8")
            req.write_text(
                old.replace("approved behavior", "revised required behavior"),
                encoding="utf-8", newline="\n",
            )
            direct = step_completion_proof(root, "STEP-001")
            assert not direct["complete"], direct
            assert "completion-contract-stale:STEP-001" in direct["reasons"], direct

            downstream = step_completion_proof(root, "STEP-002")
            assert not downstream["complete"], downstream
            assert any("dependency-incomplete:STEP-001" in value
                       for value in downstream["reasons"]), downstream
            stale_errors: list[str] = []
            _validate_task(
                root, "STEP-002", read_task(root, "STEP-002"),
                stale_errors, [],
            )
            assert not stale_errors, stale_errors
            assert render_requirements_status(root) == historical_projection
            facts = verification_dependency_facts(root, "STEP-002")
            assert len(facts) == 1 and facts[0]["complete"] is False, facts
            assert verification_context_basis(root, "STEP-002") != before_dependency
            assert verification_context_basis(root, "STEP-003") == before_unrelated
            assert step_completion_proof(root, "STEP-003")["complete"]

            # После новой upstream Verification/REVIEW прежний downstream PASS
            # не должен снова стать valid. Его immutable REVIEW помнит старый
            # dependency completion basis, даже если upstream снова complete.
            first_review_basis = basis["STEP-001"]
            first_review_path = review_paths["STEP-001"]
            basis["STEP-001"] = planning_context_basis(root, "STEP-001")
            new_report = root / "planning/reviews/STEP-001/REVIEW-new-approval.md"
            write(root, "planning/reviews/STEP-001/REVIEW-new-approval.md",
                  "New independent REVIEW of revised REQ-001.\n")
            review_paths["STEP-001"] = new_report
            assert step_completion_proof(root, "STEP-001")["complete"]
            old_child = step_completion_proof(root, "STEP-002")
            assert not old_child["complete"], old_child
            assert "completion-dependency-proof-stale:STEP-002" in old_child["reasons"], old_child

            # Независимый REVIEW downstream вправе связаться с новым proof.
            dependency_review_basis = dependency_completion_basis(root, "STEP-002")
            assert dependency_review_basis is not None
            assert step_completion_proof(root, "STEP-002")["complete"]

            # Вернуть исторические proof snapshots для следующих сценариев.
            basis["STEP-001"] = first_review_basis
            review_paths["STEP-001"] = first_review_path
            req.write_text(old, encoding="utf-8", newline="\n")
            dependency_review_basis = dependency_completion_basis(root, "STEP-002")

            # Изменение обратной traceability metadata не меняет semantic
            # contract: связанный STEP не инвалидируется без основания.
            req.write_text(old, encoding="utf-8", newline="\n")
            assert step_completion_proof(root, "STEP-001")["complete"]
            assert verification_context_basis(root, "STEP-002") == before_dependency

            # Известные cycles никогда не становятся доказанным completion.
            first = root / "planning/tasks/STEP-001.md"
            first.write_text(
                first.read_text(encoding="utf-8").replace(
                    "depends_on: []", "depends_on:\n  - STEP-002", 1,
                ),
                encoding="utf-8", newline="\n",
            )
            cyclic = step_completion_proof(root, "STEP-002")
            assert not cyclic["complete"], cyclic
            assert "dependency-cycle:" in str(cyclic["reasons"]), cyclic
            assert step_completion_proof(root, "STEP-003")["complete"]

            # Missing upstream STEP не должен давать ложный completion PASS
            # и не должен затрагивать несвязанный STEP-003.
            first.write_text(
                first.read_text(encoding="utf-8").replace(
                    "depends_on:\n  - STEP-002", "depends_on: []", 1,
                ),
                encoding="utf-8", newline="\n",
            )
            second = root / "planning/tasks/STEP-002.md"
            second.write_text(
                second.read_text(encoding="utf-8").replace(
                    "  - STEP-001", "  - STEP-999", 1,
                ),
                encoding="utf-8", newline="\n",
            )
            missing = step_completion_proof(root, "STEP-002")
            assert not missing["complete"], missing
            assert "dependency-unprovable:STEP-999" in str(missing["reasons"]), missing
            assert step_completion_proof(root, "STEP-003")["complete"]

    # Независимая трёхуровневая цепочка: REQ-001 → STEP-001 → STEP-002
    # → STEP-003. Отдельный STEP-004 не должен получать ложный stale.
    # В отличие от прямого сценария выше, это доказывает транзитивность
    # и предотвращает повторное принятие старого REVIEW на втором уровне.
    with tempfile.TemporaryDirectory(prefix="harness-dependency-multihop-") as tmp:
        root = Path(tmp)
        write(root, ".harness/manifest.yaml", MANIFEST)
        for number in range(1, 5):
            step_id, req_id = f"STEP-{number:03d}", f"REQ-{number:03d}"
            dependency = {2: "STEP-001", 3: "STEP-002"}.get(number)
            write(root, f"docs/requirements/{req_id}-fixture.md",
                  requirement(step_id, req_id))
            write(root, f"planning/tasks/{step_id}.md",
                  step(step_id, req_id, dependency))
            write(root, f"planning/reviews/{step_id}/REVIEW-proof.md",
                  "Original immutable REVIEW.\n")

        original_basis = {
            f"STEP-{number:03d}": planning_context_basis(root, f"STEP-{number:03d}")
            for number in range(1, 5)
        }
        review_paths = {
            f"STEP-{number:03d}": root / f"planning/reviews/STEP-{number:03d}/REVIEW-proof.md"
            for number in range(1, 5)
        }
        dependency_bases: dict[str, str] = {}
        modern_parent_without_proof = False

        def trusted_multihop(_root: Path, step_id: str, **_kwargs):
            meta = {"contract_basis": original_basis[step_id]}
            if step_id in dependency_bases:
                meta["dependency_completion_basis"] = dependency_bases[step_id]
            if step_id == "STEP-002" and modern_parent_without_proof:
                meta["reviewed_subject_content_hash"] = "sha256:" + "2" * 64
            return {
                "path": review_paths[step_id],
                "verdict": "PASS",
                "document": {"frontmatter": meta},
            }

        with patch("review_contract.latest_trusted_review", side_effect=trusted_multihop):
            # Два legacy REPORT подряд: nested dependency-incomplete тоже
            # является только историческим предупреждением, не PASS proof.
            legacy_chain = step_completion_proof(root, "STEP-003")
            assert not legacy_chain["complete"], legacy_chain
            legacy_errors: list[str] = []
            legacy_warnings: list[str] = []
            _validate_task(
                root, "STEP-003", read_task(root, "STEP-003"),
                legacy_errors, legacy_warnings,
            )
            assert not any("completed STEP completion proof failed" in value
                           for value in legacy_errors), legacy_errors
            assert not legacy_warnings, legacy_warnings

            # Modern parent с отсутствующей dependency basis не получает
            # grandfathering через исторический downstream.
            modern_parent_without_proof = True
            invalid_errors: list[str] = []
            _validate_task(
                root, "STEP-003", read_task(root, "STEP-003"),
                invalid_errors, [],
            )
            assert any("dependency-incomplete:STEP-002" in x
                       for x in invalid_errors), invalid_errors
            modern_parent_without_proof = False

            # Каждый REVIEW фиксирует proofs upstream, действительные
            # именно в момент создания отчёта.
            dependency_bases["STEP-002"] = dependency_completion_basis(root, "STEP-002")
            dependency_bases["STEP-003"] = dependency_completion_basis(root, "STEP-003")
            for number in range(1, 5):
                proof = step_completion_proof(root, f"STEP-{number:03d}")
                assert proof["complete"], proof

            before_chain = verification_context_basis(root, "STEP-003")
            before_unrelated = verification_context_basis(root, "STEP-004")
            req = root / "docs/requirements/REQ-001-fixture.md"
            req.write_text(
                req.read_text(encoding="utf-8").replace(
                    "approved behavior", "new approved behavior"
                ),
                encoding="utf-8", newline="\n",
            )

            for step_id in ("STEP-001", "STEP-002", "STEP-003"):
                assert not step_completion_proof(root, step_id)["complete"], step_id
            third = step_completion_proof(root, "STEP-003")
            assert "dependency-incomplete:STEP-002" in str(third["reasons"]), third
            assert verification_context_basis(root, "STEP-003") != before_chain
            assert verification_context_basis(root, "STEP-004") == before_unrelated
            assert step_completion_proof(root, "STEP-004")["complete"]

            # Сначала заново подтверждается STEP-001. Это ещё не делает
            # действительными исторические REVIEW у STEP-002/003.
            original_basis["STEP-001"] = planning_context_basis(root, "STEP-001")
            review_paths["STEP-001"] = (
                root / "planning/reviews/STEP-001/REVIEW-new.md"
            )
            write(root, "planning/reviews/STEP-001/REVIEW-new.md", "New REQ review.\n")
            assert step_completion_proof(root, "STEP-001")["complete"]
            assert not step_completion_proof(root, "STEP-002")["complete"]
            assert not step_completion_proof(root, "STEP-003")["complete"]

            # REVIEW STEP-002 теперь фиксирует новый upstream proof.
            dependency_bases["STEP-002"] = dependency_completion_basis(root, "STEP-002")
            review_paths["STEP-002"] = (
                root / "planning/reviews/STEP-002/REVIEW-new.md"
            )
            write(root, "planning/reviews/STEP-002/REVIEW-new.md", "New parent review.\n")
            assert step_completion_proof(root, "STEP-002")["complete"]

            # Старый REVIEW STEP-003 всё ещё привязан к прежнему
            # STEP-002 proof; реальное завершение требует своего REVIEW.
            stale_third = step_completion_proof(root, "STEP-003")
            assert not stale_third["complete"], stale_third
            assert "completion-dependency-proof-stale:STEP-003" in stale_third["reasons"]

            dependency_bases["STEP-003"] = dependency_completion_basis(root, "STEP-003")
            review_paths["STEP-003"] = (
                root / "planning/reviews/STEP-003/REVIEW-new.md"
            )
            write(root, "planning/reviews/STEP-003/REVIEW-new.md", "New child review.\n")
            assert step_completion_proof(root, "STEP-003")["complete"]

    # Длинная линейная цепочка должна вычисляться без экспоненциального
    # повторного чтения одних и тех же STEP. До кеша каждый узел обходился
    # дважды (basis + prerequisite), приводя к ~2**depth вызовам.
    with tempfile.TemporaryDirectory(prefix="harness-dependency-depth-") as tmp:
        root = Path(tmp)
        write(root, ".harness/manifest.yaml", MANIFEST)
        depth = 12
        for number in range(1, depth + 1):
            step_id, req_id = f"STEP-{number:03d}", f"REQ-{number:03d}"
            parent = f"STEP-{number - 1:03d}" if number > 1 else None
            write(root, f"docs/requirements/{req_id}-fixture.md",
                  requirement(step_id, req_id))
            write(root, f"planning/tasks/{step_id}.md", step(step_id, req_id, parent))
            write(root, f"planning/reviews/{step_id}/REVIEW-proof.md",
                  "Original REVIEW.\n")

        plan_basis = {
            f"STEP-{number:03d}": planning_context_basis(root, f"STEP-{number:03d}")
            for number in range(1, depth + 1)
        }
        dependency_bases: dict[str, str] = {}

        def trusted_deep(_root: Path, step_id: str, **_kwargs):
            meta = {"contract_basis": plan_basis[step_id]}
            if step_id in dependency_bases:
                meta["dependency_completion_basis"] = dependency_bases[step_id]
            return {
                "path": root / f"planning/reviews/{step_id}/REVIEW-proof.md",
                "verdict": "PASS",
                "document": {"frontmatter": meta},
            }

        with patch("review_contract.latest_trusted_review", side_effect=trusted_deep):
            for number in range(2, depth + 1):
                step_id = f"STEP-{number:03d}"
                dependency_bases[step_id] = dependency_completion_basis(root, step_id)

            # Считаем реальные чтения canonical task, а не время выполнения:
            # результат не зависит от нагрузки на CI runner или платформы.
            import planning_contract

            with patch("planning_contract.read_task", wraps=planning_contract.read_task) as spy:
                deepest = step_completion_proof(root, f"STEP-{depth:03d}")
            assert deepest["complete"], deepest
            assert spy.call_count < 120, (
                f"completion proof revisited task files {spy.call_count} times "
                f"for a {depth}-step chain"
            )

    historical_publication_regression()
    blocked_dag_regression()
    print("DEPENDENCY EVIDENCE ENFORCEMENT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
