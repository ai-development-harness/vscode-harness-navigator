import * as assert from 'node:assert/strict';
import * as path from 'node:path';
import * as vscode from 'vscode';
import {
  activateExtension,
  folderByName,
  refresh,
  pollFor,
  isRussian,
  type ExtensionSeams,
} from '../support/helpers';
import { originalFs, writeText, removePath } from '../support/originalApis';
import { assertIsolatedWorkspace } from '../support/workspaceGuard';
import { BoundarySpies } from '../support/boundarySpies';
import { extensionPath } from '../support/helpers';

suite('Project State dependency Graph: production Extension Host/VSIX', () => {
  let seams: ExtensionSeams, root: vscode.WorkspaceFolder, other: vscode.WorkspaceFolder;
  suiteSetup(async () => {
    assertIsolatedWorkspace();
    seams = await activateExtension();
    root = folderByName('mvp-valid');
    other = folderByName('mvp-degraded');
    await refresh();
  });

  /** Проверяем локализованный panel и публичную taxonomy на настоящем Host, включая VSIX. */
  async function assertGraphError(reason: string, category: string, en: string, ru: string) {
    await pollFor(() => seams.getActiveDependencyGraphSnapshot(root)?.error === reason, reason);
    const message = isRussian() ? ru : en;
    assert.equal(seams.getDependencyGraphPanelSnapshot(root)?.model.error, message);
    const report = await vscode.commands.executeCommand<{
      graphDiagnostics: { workspaceRoot: string; category: string; message: string }[];
    }>('harnessNavigator.showDiagnostics');
    assert.ok(
      report?.graphDiagnostics.some(
        (d) =>
          d.workspaceRoot === root.uri.fsPath && d.category === category && d.message === message,
      ),
    );
  }

  test('Host Workspace Trust seam запрещает Python и локализует restricted-mode graph', async () => {
    const descriptor = Object.getOwnPropertyDescriptor(vscode.workspace, 'isTrusted');
    assert.ok(descriptor);
    const spies = new BoundarySpies();
    spies.install(path.join(extensionPath(), 'dist/extension.js'));
    try {
      // Меняется только Host API fact; production service и fixed process boundary не подменяются.
      Object.defineProperty(vscode.workspace, 'isTrusted', { configurable: true, value: false });
      await refresh();
      await vscode.commands.executeCommand('harnessNavigator.showDependencyGraph', {
        folder: other,
      });
      assert.equal(seams.getActiveDependencyGraphSnapshot(root)?.kind, 'untrusted');
      assert.equal(
        spies.recordsFor('child_process.spawn').filter((r) => r.extensionOriginated).length,
        0,
      );
      assert.equal(
        seams.getDependencyGraphPanelSnapshot(other)?.model.error,
        isRussian()
          ? 'Project State API требует доверенный workspace.'
          : 'Project State API requires a trusted workspace.',
      );
    } finally {
      Object.defineProperty(vscode.workspace, 'isTrusted', descriptor);
      spies.restore();
      await refresh();
    }
  });

  test('реальный fixed Python API даёт degraded/MISSING/cycle/provenance, локализованный SVG panel', async () => {
    const spies = new BoundarySpies();
    spies.install(path.join(extensionPath(), 'dist/extension.js'));
    try {
      await refresh();
      await vscode.commands.executeCommand('harnessNavigator.showDependencyGraph', {
        folder: root,
      });
      const snapshot = seams.getActiveDependencyGraphSnapshot(root);
      assert.equal(snapshot?.kind, 'ready');
      assert.equal(snapshot?.payload?.integrity, 'degraded');
      const panel = seams.getDependencyGraphPanelSnapshot(root);
      assert.ok(panel);
      assert.ok(panel.title.includes(root.name));
      assert.ok(panel.model.nodes.some((n) => n.kind === 'MISSING'));
      assert.deepEqual(panel.model.longestDependencyChain, ['STEP-702', 'STEP-701']);
      assert.deepEqual(panel.model.cycleMembers, ['STEP-701', 'STEP-702']);
      assert.equal(panel.model.edges.length, 4);
      assert.deepEqual(panel.model.edges[2]?.declaredBy, ['REQ-701', 'STEP-701']);
      assert.match(panel.html, /<svg/u);
      assert.match(panel.html, /id="presets"/u);
      assert.match(panel.html, /id="kinds"/u);
      assert.match(panel.html, /id="relations"/u);
      assert.match(panel.html, /id="health"/u);
      assert.match(panel.html, /navigationRevision/u);
      assert.match(panel.html, /style-src 'nonce-/u);
      assert.ok(
        panel.html.includes(
          isRussian() ? 'Самая длинная цепочка зависимостей' : 'Longest dependency chain',
        ),
      );
      assert.ok(panel.html.includes(isRussian() ? 'Уместить в окне' : 'Fit to viewport'));
      // Сохраняем фактический shipped HTML Host для отдельной visual-проверки того же renderer.
      originalFs.writeFileSync(
        `/tmp/navigator-step019-host-${isRussian() ? 'ru' : 'en'}.html`,
        panel.html,
      );
      const spawnCount = () =>
        spies.recordsFor('child_process.spawn').filter((r) => r.extensionOriginated).length;
      const beforeUi = spawnCount();
      const revision = panel.model.navigationRevision;
      await seams.dispatchDependencyGraphMessage(root, { type: 'select', id: 'STEP-701' });
      await seams.dispatchDependencyGraphMessage(root, { type: 'related', id: 'STEP-701' });
      await seams.dispatchDependencyGraphMessage(root, { type: 'reset' });
      assert.equal(spawnCount(), beforeUi, 'локальные UI messages не повторяют Project State API');
      assert.equal(seams.getDependencyGraphPanelSnapshot(root)?.model.navigationRevision, revision);
      await vscode.commands.executeCommand('harnessNavigator.showInDependencyGraph', {
        folder: root,
        artifact: { id: 'STEP-701' },
      });
      const reveal = seams.getDependencyGraphPanelSnapshot(root)?.model.navigationRevision;
      await vscode.commands.executeCommand('harnessNavigator.showInDependencyGraph', {
        folder: root,
        artifact: { id: 'STEP-701' },
      });
      assert.equal(
        seams.getDependencyGraphPanelSnapshot(root)?.model.navigationRevision,
        (reveal ?? 0) + 1,
      );
      assert.ok(
        spies.recordsFor('child_process.spawn').some((r) => r.extensionOriginated && !r.sentinel),
      );
      assert.ok(
        spies.recordsFor('vscode.window.createWebviewPanel').some((r) => r.extensionOriginated),
      );
      assert.equal(spies.violations().length, 0);
    } finally {
      spies.restore();
    }
  });

  test('context selection, canonical navigation, MISSING и independent root panels', async () => {
    await vscode.commands.executeCommand('harnessNavigator.showInDependencyGraph', {
      folder: root,
      artifact: { id: 'STEP-701' },
    });
    assert.equal(seams.getDependencyGraphPanelSnapshot(root)?.model.selectedId, 'STEP-701');
    await seams.dispatchDependencyGraphMessage(root, { type: 'open', id: 'STEP-701' });
    assert.equal(
      vscode.window.activeTextEditor?.document.uri.fsPath,
      path.join(root.uri.fsPath, 'planning/tasks/STEP-701.md'),
    );
    await seams.dispatchDependencyGraphMessage(root, { type: 'reset' });
    await seams.dispatchDependencyGraphMessage(root, { type: 'select', id: 'MISSING:REQ-999' });
    const before = vscode.window.activeTextEditor?.document.uri.toString();
    await seams.dispatchDependencyGraphMessage(root, { type: 'open', id: 'MISSING:REQ-999' });
    assert.equal(vscode.window.activeTextEditor?.document.uri.toString(), before);
    await vscode.commands.executeCommand('harnessNavigator.showDependencyGraph', { folder: other });
    assert.ok(seams.getDependencyGraphPanelSnapshot(other)?.title.includes(other.name));
    assert.ok(seams.getDependencyGraphPanelSnapshot(root)?.title.includes(root.name));
    await seams.dispatchDependencyGraphMessage(root, { type: 'reset' });
  });

  test('BLOCKED/future schema/malformed не имеют fallback; watcher восстанавливает API per root', async () => {
    const uri = vscode.Uri.joinPath(root.uri, '.harness/project-state-fixture.json');
    const original = originalFs.readFileSync(uri.fsPath, 'utf8');
    const payload = JSON.parse(original) as Record<string, unknown>;
    const otherSnapshot = seams.getActiveDependencyGraphSnapshot(other);
    try {
      for (const [text, reason, category, en, ru] of [
        [
          JSON.stringify({ ...payload, status: 'BLOCKED' }),
          'blocked',
          'ProjectStateBlocked',
          'Project State API is BLOCKED.',
          'Project State API заблокирован (BLOCKED).',
        ],
        [
          JSON.stringify({ ...payload, schemaVersion: 2 }),
          'unsupportedSchema',
          'ProjectStateUnsupportedSchema',
          'Project State API schema is unsupported.',
          'Схема Project State API не поддерживается.',
        ],
        [
          'bad json',
          'malformed',
          'ProjectStateReadError',
          'Project State API returned malformed JSON.',
          'Project State API вернул некорректный JSON.',
        ],
      ] as const) {
        await writeText(uri, text);
        await refresh();
        await assertGraphError(reason, category, en, ru);
        assert.equal(seams.getActiveDependencyGraphSnapshot(root)?.kind, 'error');
        if (text.includes('BLOCKED'))
          assert.equal(seams.getActiveDependencyGraphSnapshot(root)?.error, 'blocked');
        assert.equal(seams.getActiveDependencyGraphSnapshot(root)?.payload, undefined);
        assert.equal(seams.getDependencyGraphPanelSnapshot(root)?.model.nodes.length, 0);
      }
      // Только watcher: refresh здесь намеренно не используется.
      await writeText(uri, original);
      await pollFor(
        () => seams.getActiveDependencyGraphSnapshot(root)?.kind === 'ready',
        'Project State watcher recovery',
      );
      const stableOther = seams.getActiveDependencyGraphSnapshot(other);
      const stableRoot = seams.getActiveDependencyGraphSnapshot(root);
      await writeText(uri, original.replace('graph-fixture', 'changed-graph'));
      await pollFor(
        () =>
          seams.getActiveDependencyGraphSnapshot(root) !== undefined &&
          seams.getActiveDependencyGraphSnapshot(root) !== stableRoot,
        'owning root update',
      );
      assert.equal(
        seams.getActiveDependencyGraphSnapshot(other),
        stableOther,
        'другой root не должен обновляться от чужого watcher',
      );
      assert.ok(otherSnapshot);
    } finally {
      await writeText(uri, original);
      await refresh();
    }
  });

  test('WebView refresh сохраняет unsupported/invalid blocker и восстанавливается после исправления', async () => {
    await vscode.commands.executeCommand('harnessNavigator.showDependencyGraph', { folder: root });
    const uri = vscode.Uri.joinPath(root.uri, '.harness/manifest.yaml');
    const original = originalFs.readFileSync(uri.fsPath, 'utf8');
    const spies = new BoundarySpies();
    spies.install(path.join(extensionPath(), 'dist/extension.js'));
    try {
      for (const [manifest, reason] of [
        [original.replace("'0.10.3'", "'0.10.2'"), 'unsupportedHarness'],
        ['invalid: [', 'unavailable'],
      ] as const) {
        await writeText(uri, manifest);
        // Не ждём watcher и не вызываем global Refresh: eligibility проверяется перед process.
        await seams.dispatchDependencyGraphMessage(root, { type: 'refresh' });
        assert.equal(seams.getActiveDependencyGraphSnapshot(root)?.error, reason);
        assert.equal(seams.getDependencyGraphPanelSnapshot(root)?.model.nodes.length, 0);
      }
      assert.equal(
        spies.recordsFor('child_process.spawn').filter((r) => r.extensionOriginated).length,
        0,
      );
    } finally {
      spies.restore();
      await writeText(uri, original);
      await seams.dispatchDependencyGraphMessage(root, { type: 'refresh' });
      assert.equal(seams.getActiveDependencyGraphSnapshot(root)?.kind, 'ready');
      await refresh();
    }
  });

  const failures: {
    reason: string;
    category: string;
    en: string;
    ru: string;
    script?: string;
    withoutTool?: boolean;
    withoutPython?: boolean;
  }[] = [
    {
      reason: 'missingTool',
      category: 'ProjectStateUnavailable',
      en: 'Project State API tool is unavailable.',
      ru: 'Инструмент Project State API недоступен.',
      withoutTool: true,
    },
    {
      reason: 'missingPython',
      category: 'ProjectStatePythonUnavailable',
      en: 'Python 3 is unavailable.',
      ru: 'Python 3 недоступен.',
      withoutPython: true,
    },
    {
      reason: 'timeout',
      category: 'ProjectStateTimeout',
      en: 'Project State API timed out.',
      ru: 'Истекло время ожидания Project State API.',
      script: 'import time\ntime.sleep(30)\n',
    },
    {
      reason: 'oversizedOutput',
      category: 'ProjectStateOutputTooLarge',
      en: 'Project State API output exceeds the size limit.',
      ru: 'Ответ Project State API превышает допустимый размер.',
      script: 'print("x" * 1048577)\n',
    },
    {
      reason: 'processError',
      category: 'ProjectStateReadError',
      en: 'Project State API process failed.',
      ru: 'Процесс Project State API завершился с ошибкой.',
      script: 'import sys\nsys.exit(7)\n',
    },
  ];
  for (const failure of failures) {
    test(`реальный process ${failure.reason}: локализация panel и Show Diagnostics RU/EN`, async () => {
      await vscode.commands.executeCommand('harnessNavigator.showDependencyGraph', {
        folder: root,
      });
      const tool = vscode.Uri.joinPath(root.uri, '.harness/tools/project-state.py');
      const original = originalFs.readFileSync(tool.fsPath, 'utf8');
      const originalPath = process.env.PATH;
      try {
        if (failure.withoutTool) await removePath(tool);
        else if (failure.script) await writeText(tool, failure.script);
        if (failure.withoutPython) process.env.PATH = path.join(root.uri.fsPath, 'no-python');
        await seams.dispatchDependencyGraphMessage(root, { type: 'refresh' });
        await assertGraphError(failure.reason, failure.category, failure.en, failure.ru);
      } finally {
        if (originalPath === undefined) delete process.env.PATH;
        else process.env.PATH = originalPath;
        await writeText(tool, original);
        await refresh();
      }
    });
  }
});
