---
name: security-review
description: Perform adversarial security analysis with concrete attack scenarios and regression-test recommendations.
---
# security-review

Используй только для security-sensitive scope/factual diff. Проверяй authentication/authorization, IDOR/tenant scoping, injections, SSRF, XSS/CSRF where applicable, secrets, path/file/network boundaries, deserialization, privilege escalation, supply chain и data exposure. Для каждого finding: severity, preconditions, attack scenario, impact, mitigation, regression test. Не добавляй спекулятивный шум.
