---
name: code-review
description: Perform evidence-based review of the supplied production change surface, report all material reproducible defects, and avoid cosmetic or speculative blocking findings.
---
# code-review

Проверяй только фактически предоставленный review surface/diff/revision и релевантный surrounding code; не расширяй scope произвольно.

## Приоритет

Ищи прежде всего:

- correctness и data corruption;
- authorization/ownership violations;
- concurrency/transactions/async lifecycle;
- error handling и recovery;
- compatibility/API/data migration regressions;
- meaningful performance regressions;
- test gaps, из-за которых material behavior остаётся недоказанным.

Style/cosmetic замечание не является blocking finding, если оно не создаёт конкретный defect/risk.

## Finding contract

Для каждого material finding укажи:

- severity;
- точный location;
- конкретный воспроизводимый scenario/preconditions;
- observable impact;
- почему existing code/tests это допускают;
- fix direction;
- для high/critical — regression-test idea, если её можно сформулировать без выдумывания project tooling.

Сделай полный semantic проход доступного review surface и верни **все обнаруженные material findings за этот проход**, а не останавливайся после первого.

Если проблему нельзя связать с конкретным сценарием/impact или доказательством в текущем surface, не повышай её до blocking finding; при необходимости пометь как non-blocking observation.
