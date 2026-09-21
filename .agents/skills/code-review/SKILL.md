---
name: code-review
description: Perform evidence-based production code review focused on real defects rather than cosmetic style comments.
---
# code-review

Приоритет: correctness, data corruption, authorization, concurrency, transactions, async lifecycle, error handling, compatibility, performance path и meaningful test gaps. Для finding укажи severity/location/concrete scenario/impact/fix direction. Если проблему нельзя объяснить конкретным сценарием — не повышай её до blocking finding. Для high/critical по возможности укажи regression test idea.
