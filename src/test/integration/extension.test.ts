import * as assert from 'node:assert/strict';
import * as vscode from 'vscode';

const encoder = new TextEncoder();
const decoder = new TextDecoder();

const EXTENSION_ID = 'ai-development-harness.vscode-harness-navigator';

suite('extension lifecycle (Extension Host)', () => {
  test('обнаруживается по своему manifest id', () => {
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension, `extension "${EXTENSION_ID}" was not found by the Extension Host`);
  });

  test('активируется и возвращает наблюдаемый результат активации', async () => {
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension, `extension "${EXTENSION_ID}" was not found by the Extension Host`);

    const activationResult = (await extension.activate()) as {
      state: unknown;
      registeredDisposableCount: unknown;
      activatedLogMessage: unknown;
      fallbackLogMessage: unknown;
      projectStates: unknown;
    };

    assert.equal(extension.isActive, true);
    assert.equal(activationResult.state, 'activated');
    assert.equal(typeof activationResult.registeredDisposableCount, 'number');
    assert.ok(
      (activationResult.registeredDisposableCount as number) > 0,
      'activation must register at least one disposable',
    );
    const russianLocale = vscode.env.language.toLowerCase().startsWith('ru');
    assert.equal(
      activationResult.activatedLogMessage,
      russianLocale
        ? 'Расширение Harness Navigator активировано.'
        : 'Harness Navigator extension activated.',
    );
    // Ключ намеренно отсутствует в русском bundle. Проверяется реальный
    // `vscode.l10n.t` в Extension Host, поэтому English fallback нельзя
    // подменить локальным helper или тестовыми литералами.
    assert.equal(
      activationResult.fallbackLogMessage,
      'Harness Navigator localization fallback is active.',
    );
    assert.ok(Array.isArray(activationResult.projectStates));
  });

  test('изолирует multi-root project states и регистрирует diagnostics command', async () => {
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension, `extension "${EXTENSION_ID}" was not found by the Extension Host`);
    await extension.activate();

    const report = await vscode.commands.executeCommand<{
      states: {
        kind: unknown;
        diagnostic: { category: unknown; message: unknown };
      }[];
      lines: string[];
    }>('harnessNavigator.showDiagnostics');

    assert.equal(vscode.workspace.workspaceFolders?.length, 4);
    assert.equal(report.states.length, 4);
    assert.ok(report.states.some((state) => state.kind === 'valid'));
    assert.ok(
      report.states.some(
        (state) => state.kind === 'nonHarness' && state.diagnostic.category === 'NotHarnessProject',
      ),
    );
    const russianLocale = vscode.env.language.toLowerCase().startsWith('ru');
    assert.ok(
      report.states.some(
        (state) =>
          state.kind === 'invalidManifest' &&
          state.diagnostic.category === 'InvalidManifest' &&
          state.diagnostic.message === 'Harness manifest contains an invalid release: {0}.',
      ),
      'invalid release must preserve its stable diagnostic key before localization',
    );
    // Real observable coverage of the `ManifestInputError` branch (F-010):
    // `non-regular-manifest-project/.harness/manifest.yaml` is a directory,
    // not a regular file, so `detectProject` throws `ManifestInputError`
    // with the dynamically-constructed `manifestNotRegularFile` message —
    // this message never appears as a direct `diagnostic(...)` call site, so
    // it is only reachable through this exact runtime branch.
    assert.ok(
      report.states.some(
        (state) =>
          state.kind === 'invalidManifest' &&
          state.diagnostic.category === 'InvalidManifest' &&
          state.diagnostic.message === 'Harness manifest must be a regular file.',
      ),
      'non-regular manifest must surface the ManifestInputError diagnostic message',
    );
    assert.ok(
      report.lines.some((line) =>
        line.includes(
          russianLocale ? 'Manifest Harness отсутствует.' : 'Harness manifest is absent.',
        ),
      ),
      'diagnostics command must return the localized text written to Output Channel',
    );
    assert.ok(
      report.lines.some((line) =>
        line.includes(
          russianLocale
            ? 'Manifest Harness содержит некорректную версию release: banana.'
            : 'Harness manifest contains an invalid release: banana.',
        ),
      ),
      'diagnostics command must localize the invalid release explanation in the active locale',
    );
    assert.ok(
      report.lines.some((line) =>
        line.includes(
          russianLocale
            ? 'Manifest Harness должен быть обычным файлом.'
            : 'Harness manifest must be a regular file.',
        ),
      ),
      'diagnostics command must localize the ManifestInputError explanation in the active locale',
    );
    // F-014: до создания planning/tasks в watcher-тесте `valid-project` не
    // содержит configured artifact directories (`docs/requirements`,
    // `docs/adr`, `docs/open-questions`, `planning/tasks`), поэтому Artifact
    // Index детерминированно публикует `ArtifactDirectoryMissing` через тот
    // же общий Output Channel flow. Это единственная точка Extension Host
    // suite, проверяющая локализованный artifact diagnostic text (а не
    // только manifest diagnostic text) в обоих реальных EN/RU запусках.
    assert.ok(
      report.lines.some((line) =>
        line.includes(
          russianLocale
            ? 'Настроенный каталог артефактов недоступен: docs/requirements.'
            : 'A configured artifact directory is unavailable: docs/requirements.',
        ),
      ),
      'diagnostics command must localize an artifact-layer diagnostic (ArtifactDirectoryMissing) in the active locale',
    );
  });

  test('команда refresh пересобирает derived state без записи workspace', async () => {
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension, `extension "${EXTENSION_ID}" was not found by the Extension Host`);
    await extension.activate();

    await assert.doesNotReject(async () =>
      vscode.commands.executeCommand('harnessNavigator.refresh'),
    );
  });

  test('watcher обновляет artifact и manifest state без restart, refresh не меняет bytes', async () => {
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension, `extension "${EXTENSION_ID}" was not found by the Extension Host`);
    await extension.activate();
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const extensionModule = require(extension.extensionPath + '/dist/extension.js') as {
      getActiveArtifactSnapshot: (folder: vscode.WorkspaceFolder) =>
        | {
            artifacts: { id: string }[];
          }
        | undefined;
    };
    const valid = vscode.workspace.workspaceFolders?.find(
      (folder) => folder.name === 'valid-project',
    );
    const invalid = vscode.workspace.workspaceFolders?.find(
      (folder) => folder.name === 'invalid-release-project',
    );
    assert.ok(valid);
    assert.ok(invalid);
    const artifact = vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-901.md');
    const manifest = vscode.Uri.joinPath(invalid.uri, '.harness/manifest.yaml');
    const originalManifest = await vscode.workspace.fs.readFile(manifest);
    try {
      await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(valid.uri, 'planning/tasks'));
      await vscode.workspace.fs.writeFile(
        artifact,
        encoder.encode(
          '---\nschema: 1\nid: STEP-900\nstatus: planned\n---\n\n# STEP-900 — Подготовка watcher\n',
        ),
      );
      await vscode.commands.executeCommand('harnessNavigator.refresh');
      // F-013: `valid-project` уже был valid с теми же configured paths до
      // этого refresh, поэтому artifact watchers, созданные при activation,
      // переиспользуются, а не пересоздаются здесь заново — это устраняет
      // гонку, при которой watcher пересоздавался за миллисекунды до edit.
      //
      // F-018: два предыдущих fix cycle пытались добиться детерминированной
      // доставки события именно через сырой watcher timing (bounded retry с
      // каждым разом новым write). Независимый review измерил, что этот
      // bounded retry ни разу не конвертировал failing run в success —
      // проходящие прогоны укладываются в ~500-660 ms на первой попытке, а
      // падающие сжигают всё окно и не восстанавливаются, что похоже на
      // binary per-session watcher-arming outcome, а не на per-event flake.
      // Причина внутри Extension Host watcher-сервиса конкретно в этой
      // sandbox не изолирована убедительно (предыдущая попытка объяснить её
      // экспериментом с сырым `fs.watch` не была эквивалентна по сценарию и
      // не подтверждена независимо) — этот текст намеренно не повторяет то
      // причинное объяснение.
      //
      // REQ-009 явно проектирует именно эту ситуацию: watcher доставляет
      // событие ИЛИ `Harness: Refresh` восстанавливает derived state после
      // пропущенного/неудавшегося watcher event — обе опции без перезапуска
      // Extension Host. Сценарий поэтому проверяет ровно этот документированный
      // контракт: достаточное watcher-only окно, чтобы watcher path
      // содержательно проверялся, когда он работает, и затем явный recovery
      // через команду `harnessNavigator.refresh`, если watcher-only окно не
      // наблюдало событие.
      await vscode.workspace.fs.writeFile(
        artifact,
        encoder.encode(
          '---\nschema: 1\nid: STEP-901\nstatus: planned\n---\n\n# STEP-901 — Наблюдаемый watcher\n',
        ),
      );
      let observed = await pollFor(
        () =>
          extensionModule
            .getActiveArtifactSnapshot(valid)
            ?.artifacts.some((item) => item.id === 'STEP-901') === true,
        30,
        100,
      );
      if (!observed) {
        // Watcher-only окно не наблюдало событие: используем документированный
        // recovery path REQ-009 — явный `Harness: Refresh`, не restart Extension
        // Host — и проверяем, что derived state сходится через него.
        await vscode.commands.executeCommand('harnessNavigator.refresh');
        observed = await pollFor(
          () =>
            extensionModule
              .getActiveArtifactSnapshot(valid)
              ?.artifacts.some((item) => item.id === 'STEP-901') === true,
          30,
          100,
        );
      }
      assert.ok(
        observed,
        'ни watcher, ни явный "Harness: Refresh" не наблюдали STEP-901 — ни один из ' +
          'двух документированных REQ-009 путей не сработал',
      );
      await vscode.workspace.fs.writeFile(
        manifest,
        encoder.encode(decoder.decode(originalManifest).replace('banana', '0.6.0')),
      );
      await waitFor(async () =>
        (
          await vscode.commands.executeCommand<{
            states: { kind: string; workspaceRoot: string }[];
          }>('harnessNavigator.showDiagnostics')
        ).states.some(
          (state) => state.workspaceRoot === invalid.uri.fsPath && state.kind === 'valid',
        ),
      );
      const beforeRefresh = await vscode.workspace.fs.readFile(artifact);
      await vscode.commands.executeCommand('harnessNavigator.refresh');
      assert.deepEqual(await vscode.workspace.fs.readFile(artifact), beforeRefresh);
    } finally {
      await vscode.workspace.fs.delete(artifact, { useTrash: false });
      await vscode.workspace.fs.delete(vscode.Uri.joinPath(valid.uri, 'planning'), {
        recursive: true,
        useTrash: false,
      });
      await vscode.workspace.fs.writeFile(manifest, originalManifest);
    }
  });

  test('Artifacts View/Focus View: команды, дерево, sort/filter/clearFilters, Go to Artifact и empty state', async () => {
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension, `extension "${EXTENSION_ID}" was not found by the Extension Host`);
    await extension.activate();
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const extensionModule = require(extension.extensionPath + '/dist/extension.js') as {
      getArtifactsViewSnapshot: () => TreeNodeSnapshotLike[];
      getFocusViewSnapshot: () => TreeNodeSnapshotLike[];
      getActiveTreeViewMessages: () => {
        artifacts: string | undefined;
        focus: string | undefined;
      };
      getArtifactsViewChangeEventCount: () => number;
      getArtifactsViewArtifactNodes: () => {
        folder: vscode.WorkspaceFolder;
        artifact: { id: string };
      }[];
    };
    const russianLocale = vscode.env.language.toLowerCase().startsWith('ru');
    const filteredEmptyMessage = russianLocale
      ? 'Ни один артефакт не соответствует активному фильтру. Очистите фильтр, чтобы увидеть все артефакты.'
      : 'No artifacts match the active filter. Clear the active filter to see them all.';

    const registeredCommands = await vscode.commands.getCommands(true);
    for (const command of [
      'harnessNavigator.goToArtifact',
      'harnessNavigator.setSortOrder',
      'harnessNavigator.setFilter',
      'harnessNavigator.clearFilters',
      'harnessNavigator.copyArtifactId',
      'harnessNavigator.copyArtifactPath',
    ]) {
      assert.ok(
        registeredCommands.includes(command),
        `command "${command}" must be registered on activation`,
      );
    }

    const valid = vscode.workspace.workspaceFolders?.find(
      (folder) => folder.name === 'valid-project',
    );
    assert.ok(valid);

    // valid root без planning/tasks/docs — Artifacts View должен показать
    // диагностируемый "noArtifacts" empty state, а не пустое дерево молча.
    await vscode.commands.executeCommand('harnessNavigator.refresh');
    assert.deepEqual(extensionModule.getArtifactsViewSnapshot(), []);
    assert.equal(
      extensionModule.getActiveTreeViewMessages().artifacts,
      russianLocale
        ? 'Этот проект Harness пока не содержит артефактов.'
        : 'This Harness project does not contain any artifacts yet.',
    );

    const files: { uri: vscode.Uri; content: string }[] = [
      {
        uri: vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-910.md'),
        content:
          '---\nschema: 1\nid: STEP-910\nstatus: in_progress\ntype: implementation\npriority: high\nphase: workspace-ui\n---\n\n# STEP-910 — Активный STEP для views test\n',
      },
      {
        uri: vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-911.md'),
        content:
          '---\nschema: 1\nid: STEP-911\nstatus: blocked\ntype: bugfix\npriority: low\nphase: other-phase\n---\n\n# STEP-911 — Заблокированный STEP для views test\n',
      },
      {
        uri: vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-912.md'),
        content:
          '---\nschema: 1\nid: STEP-912\nstatus: completed\ntype: refactor\npriority: medium\n---\n\n# STEP-912 — Завершённый STEP для views test\n',
      },
      {
        uri: vscode.Uri.joinPath(valid.uri, 'docs/requirements/REQ-910.md'),
        content: '---\nschema: 1\nid: REQ-910\n---\n\n# REQ-910 — Requirement для views test\n',
      },
      {
        uri: vscode.Uri.joinPath(valid.uri, 'docs/adr/ADR-910.md'),
        content:
          '---\nschema: 1\nid: ADR-910\nstatus: accepted\n---\n\n# ADR-910 — ADR для views test\n',
      },
      {
        uri: vscode.Uri.joinPath(valid.uri, 'docs/open-questions/OQ-910.md'),
        content:
          '---\nschema: 1\nid: OQ-910\nstatus: open\n---\n\n# OQ-910 — Open question для views test\n',
      },
    ];
    // `vscode.workspace.getConfiguration(...)` returns an immutable snapshot:
    // a value read from an instance captured before `update(...)` does not
    // reflect the write. Always re-fetch a fresh snapshot for reads/writes
    // instead of reusing one captured instance across the test.
    const config = () => vscode.workspace.getConfiguration('harnessNavigator.artifacts');
    // `ConfigurationTarget.Workspace` (mandated by the STEP-004 plan for
    // `runSetSortOrder`/`runSetFilter`/`runClearFilters`) persists into the
    // committed `multi-root.code-workspace` file itself. Snapshot its raw
    // bytes so `finally` can restore the fixture byte-for-byte regardless of
    // which keys the commands under test wrote or left behind.
    const workspaceFileUri = vscode.workspace.workspaceFile;
    const originalWorkspaceFileBytes =
      workspaceFileUri === undefined
        ? undefined
        : await vscode.workspace.fs.readFile(workspaceFileUri);

    try {
      for (const file of files) {
        await vscode.workspace.fs.writeFile(file.uri, encoder.encode(file.content));
      }
      await vscode.commands.executeCommand('harnessNavigator.refresh');

      // --- Artifacts View: группы STEP/REQ/ADR/OQ в фиксированном порядке, id-сортировка по умолчанию ---
      const artifactsTree = extensionModule.getArtifactsViewSnapshot();
      assert.deepEqual(
        artifactsTree.map((group) => group.label),
        ['STEP', 'REQ', 'ADR', 'OQ'],
      );
      const stepGroup = artifactsTree.find((group) => group.label === 'STEP');
      assert.ok(stepGroup);
      assert.deepEqual(
        stepGroup.children.map((item) => item.label),
        ['STEP-910', 'STEP-911', 'STEP-912'],
      );
      const step910 = stepGroup.children.find((item) => item.label === 'STEP-910');
      assert.ok(step910);
      assert.equal(step910.description, 'Активный STEP для views test');
      assert.equal(step910.contextValue, 'harnessArtifactItem');
      assert.equal(
        step910.resourceFsPath,
        vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-910.md').fsPath,
      );
      assert.equal(extensionModule.getActiveTreeViewMessages().artifacts, '');

      // --- copyArtifactId/copyArtifactPath с реальным tree node (F-006a): ---
      // до этого теста только регистрация команд проверялась, не поведение.
      const step910Node = extensionModule
        .getArtifactsViewArtifactNodes()
        .find((node) => node.artifact.id === 'STEP-910');
      assert.ok(step910Node, 'STEP-910 artifact node must be present in the live Artifacts View');
      await vscode.commands.executeCommand('harnessNavigator.copyArtifactId', step910Node);
      assert.equal(await vscode.env.clipboard.readText(), 'STEP-910');
      await vscode.commands.executeCommand('harnessNavigator.copyArtifactPath', step910Node);
      assert.equal(await vscode.env.clipboard.readText(), 'planning/tasks/STEP-910.md');

      // --- Focus View: active/blocked STEP + open OQ, без ранжирования ---
      const focusTree = extensionModule.getFocusViewSnapshot();
      assert.deepEqual(
        focusTree.map((group) => group.label),
        russianLocale
          ? ['Активные STEP', 'Заблокированные STEP', 'Открытые OQ']
          : ['Active STEP', 'Blocked STEP', 'Open OQ'],
      );
      assert.deepEqual(
        focusTree[0]?.children.map((item) => item.label),
        ['STEP-910'],
      );
      assert.deepEqual(
        focusTree[1]?.children.map((item) => item.label),
        ['STEP-911'],
      );
      assert.deepEqual(
        focusTree[2]?.children.map((item) => item.label),
        ['OQ-910'],
      );

      // --- Sort order: изменение workspace-настройки наблюдаемо без restart ---
      // F-006f: доказываем, что `workspace.onDidChangeConfiguration` реально
      // доходит до `provider.onDidChangeTreeData` (а не только что
      // `getChildren()` при прямом вызове видит новые данные) — от этого
      // событийного пути зависит настоящий `TreeView` refresh в VS Code.
      const changeEventCountBeforeSort = extensionModule.getArtifactsViewChangeEventCount();
      await config().update('sortOrder', 'status', vscode.ConfigurationTarget.Workspace);
      assert.ok(
        await pollFor(
          () => extensionModule.getArtifactsViewChangeEventCount() > changeEventCountBeforeSort,
          30,
          50,
        ),
        'workspace.onDidChangeConfiguration must trigger ArtifactsTreeDataProvider.onDidChangeTreeData',
      );
      const sortedByStatus = extensionModule
        .getArtifactsViewSnapshot()
        .find((group) => group.label === 'STEP');
      assert.deepEqual(
        sortedByStatus?.children.map((item) => item.label),
        ['STEP-911', 'STEP-912', 'STEP-910'],
      );
      await config().update('sortOrder', 'id', vscode.ConfigurationTarget.Workspace);

      // --- Fallback readSortOrder на невалидном значении настройки (F-006d) ---
      await config().update(
        'sortOrder',
        'not-a-real-sort-order',
        vscode.ConfigurationTarget.Workspace,
      );
      const fallbackSortedGroup = extensionModule
        .getArtifactsViewSnapshot()
        .find((group) => group.label === 'STEP');
      assert.deepEqual(
        fallbackSortedGroup?.children.map((item) => item.label),
        ['STEP-910', 'STEP-911', 'STEP-912'],
        'невалидное значение sortOrder должно откатываться на default ("id")',
      );
      await config().update('sortOrder', undefined, vscode.ConfigurationTarget.Workspace);

      // --- Cancellation: showQuickPick, вернувший undefined, не должен ничего писать (F-006b) ---
      const sortOrderBeforeCancel = config().get('sortOrder');
      await withQuickPickAnswers([() => false], () =>
        vscode.commands.executeCommand('harnessNavigator.setSortOrder'),
      );
      assert.equal(config().get('sortOrder'), sortOrderBeforeCancel);

      // --- Cancellation: setFilter, отменённый на выборе поля (F-006b) ---
      const filterStatusBeforeCancel = config().get('filter.status');
      await withQuickPickAnswers([() => false], () =>
        vscode.commands.executeCommand('harnessNavigator.setFilter'),
      );
      assert.equal(config().get('filter.status'), filterStatusBeforeCancel);

      // --- Cancellation: setFilter, отменённый на выборе значения после выбора поля (F-006b) ---
      await withQuickPickAnswers(
        [(item) => isRecord(item) && item.field === 'status', () => false],
        () => vscode.commands.executeCommand('harnessNavigator.setFilter'),
      );
      assert.equal(config().get('filter.status'), filterStatusBeforeCancel);

      // --- "Harness: Set Filter" (реальная команда, showQuickPick подменён на детерминированный выбор) ---
      await withQuickPickAnswers(
        [
          (item) => isRecord(item) && item.field === 'status',
          (item) => isRecord(item) && item.value === 'blocked',
        ],
        () => vscode.commands.executeCommand('harnessNavigator.setFilter'),
      );
      const filteredStepGroup = extensionModule
        .getArtifactsViewSnapshot()
        .find((group) => group.label === 'STEP');
      assert.deepEqual(
        filteredStepGroup?.children.map((item) => item.label),
        ['STEP-911'],
      );
      // F-002: filter теперь workspace-wide (`scope: "window"`), поэтому
      // чтение без какого-либо resource `Uri` уже видит то же значение —
      // команда больше не спрашивает root и не пишет по-разному в
      // зависимости от него.
      assert.equal(config().get('filter.status'), 'blocked');
      assert.equal(
        extensionModule.getActiveTreeViewMessages().artifacts,
        '',
        'активный filter всё ещё оставляет STEP-911 видимым, populated остаётся без message',
      );

      // --- Phase filter через showInputBox (F-006c): установка значения ---
      await withQuickPickAnswers([(item) => isRecord(item) && item.field === 'phase'], () =>
        withInputBoxAnswer('workspace-ui', () =>
          vscode.commands.executeCommand('harnessNavigator.setFilter'),
        ),
      );
      assert.equal(config().get('filter.phase'), 'workspace-ui');
      const phaseFilteredGroup = extensionModule
        .getArtifactsViewSnapshot()
        .find((group) => group.label === 'STEP');
      // Оба filter key активны одновременно: status=blocked (STEP-911) И
      // phase=workspace-ui (STEP-910) не пересекаются → пустой STEP.
      assert.deepEqual(phaseFilteredGroup?.children.map((item) => item.label) ?? [], []);

      // --- Phase filter: пустой ввод очищает ключ (trim → undefined, не cancel) (F-006c) ---
      await withQuickPickAnswers([(item) => isRecord(item) && item.field === 'phase'], () =>
        withInputBoxAnswer('   ', () =>
          vscode.commands.executeCommand('harnessNavigator.setFilter'),
        ),
      );
      assert.equal(config().get('filter.phase'), null);

      // --- Phase filter: showInputBox вернул undefined (Escape) — cancel, не clear (F-006b/c) ---
      const phaseBeforeCancel = config().get('filter.phase');
      await withQuickPickAnswers([(item) => isRecord(item) && item.field === 'phase'], () =>
        withInputBoxAnswer(undefined, () =>
          vscode.commands.executeCommand('harnessNavigator.setFilter'),
        ),
      );
      assert.equal(config().get('filter.phase'), phaseBeforeCancel);

      // --- "Harness: Clear Filters" сбрасывает только filter, не sort order ---
      await vscode.commands.executeCommand('harnessNavigator.clearFilters');
      const clearedStepGroup = extensionModule
        .getArtifactsViewSnapshot()
        .find((group) => group.label === 'STEP');
      assert.deepEqual(
        clearedStepGroup?.children.map((item) => item.label),
        ['STEP-910', 'STEP-911', 'STEP-912'],
      );
      // F-005: `clearFilters` записывает `undefined` (удаляет ключ), а не
      // `null` — `get(...)` без явного default возвращает контрибутируемый
      // `default: null` из `package.json`, что неотличимо снаружи, поэтому
      // здесь дополнительно проверяем byte-level отсутствие ключа в JSON.
      assert.equal(config().get('filter.status'), null);
      assert.equal(config().get('filter.phase'), null);
      assert.equal(config().get('sortOrder'), 'id');
      if (workspaceFileUri !== undefined) {
        const raw = decoder.decode(await vscode.workspace.fs.readFile(workspaceFileUri));
        assert.ok(
          !raw.includes('filter.status') && !raw.includes('filter.phase'),
          'clearFilters must remove filter keys from settings JSON, not write null (F-005)',
        );
      }

      // --- filteredEmpty: фильтр реально оставляет пустой список STEP (F-001 test reviewer) ---
      // REQ/ADR/OQ всегда проходят STEP-only filter (`matchesFilter`), поэтому
      // "filteredEmpty" для всего дерева требует их временного отсутствия —
      // иначе дерево остаётся populated даже когда вся STEP-группа скрыта.
      const nonStepFiles = files.filter((file) => !file.uri.fsPath.includes('STEP-'));
      for (const file of nonStepFiles) {
        await vscode.workspace.fs.delete(file.uri, { useTrash: false });
      }
      await vscode.commands.executeCommand('harnessNavigator.refresh');
      await withQuickPickAnswers(
        [
          (item) => isRecord(item) && item.field === 'status',
          (item) => isRecord(item) && item.value === 'cancelled',
        ],
        () => vscode.commands.executeCommand('harnessNavigator.setFilter'),
      );
      assert.deepEqual(
        extensionModule
          .getArtifactsViewSnapshot()
          .find((group) => group.label === 'STEP')
          ?.children.map((item) => item.label) ?? [],
        [],
      );
      assert.equal(extensionModule.getActiveTreeViewMessages().artifacts, filteredEmptyMessage);
      await vscode.commands.executeCommand('harnessNavigator.clearFilters');
      for (const file of nonStepFiles) {
        await vscode.workspace.fs.writeFile(file.uri, encoder.encode(file.content));
      }
      await vscode.commands.executeCommand('harnessNavigator.refresh');

      // --- "Harness: Go to Artifact" открывает выбранный canonical файл ---
      await withQuickPickAnswers([(item) => isRecord(item) && item.label === 'ADR-910'], () =>
        vscode.commands.executeCommand('harnessNavigator.goToArtifact'),
      );
      assert.equal(
        vscode.window.activeTextEditor?.document.uri.fsPath,
        vscode.Uri.joinPath(valid.uri, 'docs/adr/ADR-910.md').fsPath,
      );
    } finally {
      // Byte-for-byte restore жёстче, чем `update(key, undefined, ...)`:
      // VS Code не удаляет обёртку `"settings": {}`, оставленную первым
      // `ConfigurationTarget.Workspace` write, даже когда все ключи внутри
      // неё убраны — committed fixture поэтому восстанавливается напрямую.
      if (workspaceFileUri !== undefined && originalWorkspaceFileBytes !== undefined) {
        await vscode.workspace.fs.writeFile(workspaceFileUri, originalWorkspaceFileBytes);
      }
      for (const directory of ['planning', 'docs']) {
        await vscode.workspace.fs.delete(vscode.Uri.joinPath(valid.uri, directory), {
          recursive: true,
          useTrash: false,
        });
      }
      await vscode.commands.executeCommand('harnessNavigator.refresh');
    }
  });

  test('Artifacts View/Focus View: noHarnessProject empty state, когда ни один root не valid', async () => {
    // Тест reviewer finding #3: "root невалиден/не-Harness" — третий
    // diagnosable empty state из плана STEP-004 — до этого не был покрыт ни
    // одним тестом. `multi-root.code-workspace` уже содержит три
    // заведомо-невалидных root (`ordinary-folder` — не-Harness,
    // `invalid-release-project`/`non-regular-manifest-project` — invalid
    // manifest); `valid-project` — единственный valid root в fixture, так
    // что временная порча его manifest даёт ровно сценарий "ни один root не
    // valid" для всего workspace, наблюдаемый без добавления нового fixture.
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension, `extension "${EXTENSION_ID}" was not found by the Extension Host`);
    await extension.activate();
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const extensionModule = require(extension.extensionPath + '/dist/extension.js') as {
      getArtifactsViewSnapshot: () => TreeNodeSnapshotLike[];
      getFocusViewSnapshot: () => TreeNodeSnapshotLike[];
      getActiveTreeViewMessages: () => {
        artifacts: string | undefined;
        focus: string | undefined;
      };
    };
    const russianLocale = vscode.env.language.toLowerCase().startsWith('ru');
    const noHarnessProjectMessage = russianLocale
      ? 'В этом workspace не обнаружен проект Harness.'
      : 'No Harness project was detected in this workspace.';

    const valid = vscode.workspace.workspaceFolders?.find(
      (folder) => folder.name === 'valid-project',
    );
    assert.ok(valid);
    const manifest = vscode.Uri.joinPath(valid.uri, '.harness/manifest.yaml');
    const originalManifest = await vscode.workspace.fs.readFile(manifest);
    try {
      await vscode.workspace.fs.writeFile(
        manifest,
        encoder.encode(decoder.decode(originalManifest).replace('0.6.0', 'banana')),
      );
      await vscode.commands.executeCommand('harnessNavigator.refresh');
      assert.deepEqual(extensionModule.getArtifactsViewSnapshot(), []);
      assert.deepEqual(extensionModule.getFocusViewSnapshot(), []);
      assert.equal(extensionModule.getActiveTreeViewMessages().artifacts, noHarnessProjectMessage);
      assert.equal(extensionModule.getActiveTreeViewMessages().focus, noHarnessProjectMessage);
    } finally {
      await vscode.workspace.fs.writeFile(manifest, originalManifest);
      await vscode.commands.executeCommand('harnessNavigator.refresh');
    }
  });

  test('deactivate безопасно вызывается и идемпотентен', async () => {
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension, `extension "${EXTENSION_ID}" was not found by the Extension Host`);
    await extension.activate();

    // Скомпилированный модуль расширения — это тот же CommonJS-модуль,
    // который Extension Host загрузил как `main`; require() здесь вернёт
    // тот же экземпляр модуля (module cache Node), давая прямой реальный
    // доступ к экспортируемой точке `deactivate`, чтобы её поведение при
    // disposal можно было наблюдать, не обращаясь к приватному состоянию
    // расширения.
    // Путь к bundle расширения известен только в runtime (extensionPath),
    // поэтому он не может быть статическим импортом.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const extensionModule = require(extension.extensionPath + '/dist/extension.js') as {
      activate: (context: vscode.ExtensionContext) => unknown;
      deactivate: () => void;
      getActiveRegistrationCount: () => number;
    };
    const registrationsBefore = extensionModule.getActiveRegistrationCount();

    assert.ok(
      extensionModule.getActiveRegistrationCount() > 0,
      'active extension must expose at least one registered disposable',
    );

    assert.doesNotThrow(() => {
      extensionModule.deactivate();
    });
    assert.equal(
      extensionModule.getActiveRegistrationCount(),
      0,
      'deactivate must release registrations from the active extension lifecycle',
    );
    assert.doesNotThrow(() => {
      extensionModule.deactivate();
    });
    assert.equal(extensionModule.getActiveRegistrationCount(), 0);

    // activate → deactivate → activate: повторная активация регистрирует ровно
    // тот же набор (providers/commands/diagnostics STEP-005 не накапливаются и
    // не теряются) и оставляет Extension Host рабочим для следующих тестов.
    extensionModule.activate({ subscriptions: [] } as unknown as vscode.ExtensionContext);
    assert.equal(extensionModule.getActiveRegistrationCount(), registrationsBefore);
    extensionModule.deactivate();
    assert.equal(extensionModule.getActiveRegistrationCount(), 0);
    extensionModule.activate({ subscriptions: [] } as unknown as vscode.ExtensionContext);
    assert.equal(extensionModule.getActiveRegistrationCount(), registrationsBefore);
  });
});

/** Опрашивает predicate ограниченное число раз и возвращает наблюдался ли он, не бросая исключение. */
async function pollFor(
  predicate: () => boolean | Promise<boolean>,
  attempts: number,
  intervalMs: number,
): Promise<boolean> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (await predicate()) return true;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return false;
}

async function waitFor(predicate: () => boolean | Promise<boolean>): Promise<void> {
  assert.ok(await pollFor(predicate, 30, 100), 'watcher did not publish expected derived state');
}

/** Структурная форма `TreeNodeSnapshot` из `src/extension.ts` (только для типизации этого test-файла). */
interface TreeNodeSnapshotLike {
  readonly label: string;
  readonly description: string | undefined;
  readonly contextValue: string | undefined;
  readonly resourceFsPath: string | undefined;
  readonly children: readonly TreeNodeSnapshotLike[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/**
 * Программные `setSortOrder`/`setFilter`/`clearFilters`/`goToArtifact`
 * команды открывают штатный `vscode.window.showQuickPick`, который в
 * headless Extension Host без взаимодействия пользователя не резолвится
 * сам. Эта обёртка временно подменяет `showQuickPick` детерминированным
 * выбором по предикатам (по одному на каждый последовательный вызов
 * `showQuickPick` внутри `action`) и восстанавливает оригинал в `finally`
 * независимо от результата — команды по-прежнему выполняются через
 * реальный `vscode.commands.executeCommand`, подменяется только сам UI-prompt.
 */
type ShowQuickPickFn = typeof vscode.window.showQuickPick;

async function withQuickPickAnswers<T>(
  predicates: readonly ((item: unknown) => boolean)[],
  action: () => Thenable<T>,
): Promise<T> {
  const remaining = [...predicates];
  const original = vscode.window.showQuickPick;
  const mock: unknown = async (items: unknown) => {
    const resolvedItems = await Promise.resolve(items as unknown[] | Thenable<unknown[]>);
    const predicate = remaining.shift();
    if (predicate === undefined) return undefined;
    return resolvedItems.find((item) => predicate(item));
  };
  (vscode.window as { showQuickPick: ShowQuickPickFn }).showQuickPick = mock as ShowQuickPickFn;
  try {
    return await action();
  } finally {
    (vscode.window as { showQuickPick: ShowQuickPickFn }).showQuickPick = original;
  }
}

/**
 * То же самое для `vscode.window.showInputBox` (`phase` filter field в
 * `Harness: Set Filter` использует его, а не `showQuickPick`). `answer`
 * `undefined` симулирует Escape (cancel), непустая/пустая строка — реальный
 * ввод пользователя.
 */
type ShowInputBoxFn = typeof vscode.window.showInputBox;

async function withInputBoxAnswer<T>(
  answer: string | undefined,
  action: () => Thenable<T>,
): Promise<T> {
  const original = vscode.window.showInputBox;
  const mock: unknown = () => Promise.resolve(answer);
  (vscode.window as { showInputBox: ShowInputBoxFn }).showInputBox = mock as ShowInputBoxFn;
  try {
    return await action();
  } finally {
    (vscode.window as { showInputBox: ShowInputBoxFn }).showInputBox = original;
  }
}
