# Project Verification Driver

Harness Verification обычно доказывает STEP через deterministic commands и explicit manual checks. Для пользовательских сценариев этого недостаточно: unit/integration test может быть зелёным, хотя реальный CLI, web-flow, API или desktop surface сломан.

Project Verification Driver добавляет **project-owned способ реально запустить и пройти продукт через его публичную поверхность**. Harness Core не знает Playwright, Cypress, PTY, конкретный HTTP client или desktop automation framework — проект сам описывает, как его запускать и проверять.

## Артефакты

Project-owned:

```text
.agents/skills/verify-product/SKILL.md
docs/verification/feature-map.json
```

Local evidence, которое нельзя коммитить:

```text
.harness/local/product-verification/**
```

Harness-owned deterministic contract:

```text
.harness/tools/project-verification.py
.harness/tools/project_verification.py
```

`verify-product` намеренно **не является Core skill** и не входит в `harness-policy.required_skills`: его команды, selectors, test users, launch mode и observability принадлежат конкретному продукту.

## Driver contract

`.agents/skills/verify-product/SKILL.md` обязан иметь frontmatter:

```yaml
---
name: verify-product
description: ...
---
```

и непустые разделы:

```text
## Launch
## Doctor
## Drive
## Evidence
## Cleanup
```

- **Launch** — как поднять продукт.
- **Doctor** — read-only sanity probe перед drive.
- **Drive** — как действовать через реальную public surface.
- **Evidence** — что сохранить как наблюдаемое доказательство.
- **Cleanup** — как убрать только созданный verification state.

Core не исполняет эти инструкции самостоятельно. Semantic runtime следует project skill, а Core валидирует полученный proof.

## Feature map

`docs/verification/feature-map.json` — machine-readable связь между пользовательскими возможностями и кодом/контрактами.

Минимальный пример:

```json
{
  "schemaVersion": 1,
  "driver": {
    "skillPath": ".agents/skills/verify-product/SKILL.md",
    "primarySurface": "cli",
    "additionalSurfaces": [],
    "qualification": null
  },
  "features": [
    {
      "id": "FEATURE-STATUS",
      "title": "Inspect status",
      "surface": "cli",
      "requirements": ["REQ-001"],
      "acceptance": [
        {
          "artifact": "STEP-004",
          "criterion": "Пользователь видит текущий статус через CLI."
        }
      ],
      "sourcePaths": ["src/status.ts"],
      "sourceBasis": "sha256:...",
      "entryPoints": ["harness status"],
      "drive": ["Запустить публичную CLI-команду status."],
      "observe": ["Exit code 0 и stdout содержит текущий статус."]
    }
  ]
}
```

Поддерживаемые surfaces не предполагают browser по умолчанию:

```text
web | cli | api | desktop | mobile | library | service | other
```

Acceptance reference обязан буквально совпадать с bullet в canonical `REQ-NNN ## Acceptance` или `STEP-NNN ## Acceptance criteria`.

## Qualification

Наличие skill-файла не означает, что driver работает.

Сначала semantic runtime реально запускает хотя бы один feature через public surface и складывает evidence под `.harness/local/product-verification/`.

Затем qualification записывается детерминированно:

```bash
python3 .harness/tools/project-verification.py qualify \
  --payload-file .harness/local/product-verification/qualification.json \
  --json
```

Payload:

```json
{
  "featureId": "FEATURE-STATUS",
  "observed": "CLI вернул status=ok.",
  "evidencePaths": [".harness/local/product-verification/status.txt"]
}
```

Qualification привязана к exact SHA-256 текущего `verify-product/SKILL.md`. Изменение driver автоматически делает qualification stale.

## Drift feature map

Каждый feature хранит `sourcePaths` и `sourceBasis`. Проверка:

```bash
python3 .harness/tools/project-verification.py status --json
```

пересчитывает basis по текущим source files. Если код изменился, а feature map не был осознанно пересмотрен, результат блокируется как stale.

Это maintenance signal, а не разрешение автоматически переписывать product code:

```text
source changed
→ status = BLOCKED / stale feature
→ semantic maintenance pass
→ проверить entryPoints / drive / observe / Acceptance links
→ обновить feature map при необходимости
→ реально прогнать feature
→ re-qualify driver, если изменился сам skill
```

## STEP Verification

PLAN может использовать:

```markdown
## Verification

- command: `npm test`
- product: FEATURE-STATUS
```

`product: FEATURE-*` нужен, когда command-level tests не доказывают пользовательское поведение.

При IMPLEMENT/FIX semantic runtime выполняет project-owned driver и передаёт observation в dispatcher. Core проверяет feature, qualification current driver bytes, feature/source basis и evidence files под `.harness/local/product-verification/**`.

Без observation STEP Verification возвращает `MANUAL_REQUIRED`, а не придумывает PASS.

## REVIEW и Completion Gate

REVIEW не обязан повторно доверять prose агента. Он читает generated Verification evidence. Если `product: FEATURE-*` был частью Verification, PASS evidence содержит basis текущего driver/feature map и наблюдаемый результат.

Изменение product source после proof делает Verification stale через обычную revision freshness semantics:

```text
unit tests PASS
+ product feature proof missing/stale
→ Completion precheck BLOCKED
```

## Пример: web UI

```text
Launch  → npm run dev
Doctor  → GET /health
Drive   → открыть /login, ввести fixture credentials, submit
Evidence→ screenshot + console/network summary
Cleanup → закрыть browser/context и dev server
```

Harness Core при этом не знает selector-ов и Playwright API.

## Пример: CLI

```text
Launch  → build binary
Doctor  → app --version
Drive   → app project status
Evidence→ exact command/stdout/stderr/exit code
Cleanup → удалить только временный fixture state
```

Обе поверхности используют один deterministic feature-map/evidence contract.
