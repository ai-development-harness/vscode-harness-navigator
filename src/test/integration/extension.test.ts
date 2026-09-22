import * as assert from 'node:assert/strict';
import * as vscode from 'vscode';

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
      deactivate: () => void;
      getActiveRegistrationCount: () => number;
    };

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
  });
});
