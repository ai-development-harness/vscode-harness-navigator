---
name: write-tests
description: Design and implement focused tests that prove acceptance criteria, regressions and important edge cases using the project's real test stack.
---
# write-tests

Сначала изучи фактический test framework/conventions. Тесты должны доказывать behavior, а не implementation trivia. При bugfix сначала по возможности воспроизведи defect failing test. Учитывай negative/edge/concurrency/migration scenarios только где они релевантны. Не изобретай test command.
