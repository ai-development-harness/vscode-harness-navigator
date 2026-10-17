# Бюджет repository hardening self-test (#363)

## Исправление

`repository-hardening-self-test.py` выполняет прежнюю матрицу из 55 запусков
полного validator, но его disposable fixture теперь копирует только нужный
protocol surface. Product code и прочие произвольные tracked файлы consumer
не участвуют в этой синтетической матрице. Основной validator настоящего
checkout по-прежнему проверяет все tracked файлы.

Фильтрация включается только через `protocol_only=True` этого hardening-теста;
обычные callers `copy_effective_harness_checkout` сохраняют прежнюю full-copy
семантику, включая effective managed untracked files после updater.

Сохраняются updater-owned files, `.agents` bundles, configured templates,
skill registry, Git policy, lock, update graph и README каталога отчётов.
Все relocated paths разрешаются через `harness_config`. Затем выполняется
прежняя isolation: project artifacts удаляются, lifecycle возвращается в
pre-INIT, templates восстанавливаются из protocol definitions, projections
пересобираются. Исходный checkout не изменяется.

Матрица не сокращена: EOF во всех режимах, conflict markers, YAML parsing,
forbidden paths, secrets в working tree/index/binary, ignore semantics,
policy/updater ownership/runtime restrictions и dispatcher Verification boundary.
Изоляция initialized/customized templates сохраняет регрессии #191 и #254.

## Бюджет и диагностика

Лимит runner остаётся **120 секунд** на self-test; workflows его не повышают.
Каждый validator invocation hardening-теста печатает flushed marker вида
`[SCENARIO] validator-27/manual`. При timeout runner сообщает последний marker,
длительность и лимит; не выдаёт неограниченный raw log. Assertion failure остаётся
FAIL с exit code, истечение бюджета — TIMEOUT без retry. POSIX timeout убивает
оставшуюся process group даже после выхода родителя, чтобы inherited pipes
не оставляли `communicate()` зависшим.

Обычная проверка:

```bash
python3 .harness/tools/repository-hardening-self-test.py
python3 .harness/tools/run-self-tests-self-test.py
python3 .harness/tools/self-test-fixture-self-test.py
python3 .harness/tools/run-self-tests.py --timeout-seconds 120
```

## Измерения

Полный before/after набор и ограничения приведены в
[`evidence/issue-363/README.md`](evidence/issue-363/README.md).
Измерения — evidence конкретной среды, а не универсальная гарантия времени
для любого runner. Прохождение supported Python 3.11/3.13 и downstream upgrade
дополнительно подтверждается обязательной release qualification.
