# Stress Suite

Harness release qualification имеет отдельный bounded stress gate для race/process/locking/cleanup сценариев.

## Почему это отдельный suite

Обычный synthetic self-test доказывает один deterministic run. Для intermittent defect этого недостаточно: regression #256 проявлялся только на части запусков cleanup временного Git repository после concurrent process activity.

Stress suite не повторяет весь Harness N раз. Он содержит только явно выбранные concurrency/process-sensitive scenarios.

## Canonical manifest

`.harness/stress-tests.json` — source of truth stress scenarios.

Каждый scenario указывает:

- stable `id`;
- локальный `*-self-test.py` tool;
- argv без shell;
- ровно один `{iterations}` placeholder;
- bounded timeout.

Первый scenario — `concurrent-authority-cleanup`, regression для #256.

## Canonical command

Release-level default:

~~~bash
python3 .harness/tools/run-stress-tests.py --json
~~~

Manifest задаёт `defaultIterations: 20`.

Лёгкий PR/compatibility run может явно уменьшить budget:

~~~bash
python3 .harness/tools/run-stress-tests.py --iterations 5
~~~

Iterations меньше release default допустимы только для non-release CI. Release Qualification не передаёт уменьшенное значение.

## Failure semantics

Runner:

- запускает каждый scenario ровно один раз с requested bounded iteration count;
- не делает retry после failure;
- не использует sleep как лечение race;
- timeout завершает process tree и делает suite красным;
- non-zero child exit делает suite красным;
- сохраняет exit code, hashes/sizes stdout/stderr и bounded tails failed scenario.

Если cleanup внутри scenario падает, его non-zero exit не подавляется и не повторяется автоматически.

## Release Qualification

`release-qualification.py --lane current` запускает full stress suite с 20 iterations как отдельный mandatory gate после validator + full synthetic suite.

Поэтому PASS current release lane означает, что bounded stress gate также был выполнен. Minimum Python/Windows compatibility остаются отдельными lanes.

## Расширение manifest

Новый scenario добавляется только если defect/contract чувствителен к concurrency, subprocess lifecycle, locks, temporary Git repositories, atomic filesystem semantics или cleanup races.

Нельзя добавлять обычный deterministic unit/regression test только ради многократного запуска: он должен оставаться в discoverable `run-self-tests.py`.
