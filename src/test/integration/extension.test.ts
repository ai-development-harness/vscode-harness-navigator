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
