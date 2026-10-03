---
name: security-review
description: Perform adversarial review of a security-sensitive factual change surface using explicit trust boundaries, attacker preconditions, concrete exploit scenarios and regression evidence.
---
# security-review

Используй только для security-sensitive scope/factual diff. Не превращай общий hardening checklist в findings без связи с фактической поверхностью изменения.

## Сначала восстанови boundary

Определи применимые:

- protected assets/data;
- caller/user/tenant identities и permission boundaries;
- external input/file/path/network boundaries;
- privileged operations;
- third-party/supply-chain boundary.

Проверяй authentication/authorization, IDOR/tenant scoping, injections, SSRF, XSS/CSRF where applicable, secrets, path/file/network boundaries, deserialization, privilege escalation, supply chain и data exposure **только там, где соответствующая поверхность реально существует**.

## Finding contract

Для каждого material finding укажи:

- severity;
- affected asset/boundary;
- attacker preconditions/capabilities;
- concrete attack scenario;
- observable impact;
- evidence/location;
- mitigation/fix direction;
- regression test или проверку, способную доказать исправление.

Отделяй concrete vulnerability от generic hardening suggestion. Если exploit path нельзя обосновать по текущему factual surface, не выдавай спекуляцию за security finding.
