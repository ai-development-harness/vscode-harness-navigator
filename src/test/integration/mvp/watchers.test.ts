import * as assert from 'node:assert/strict';
import * as vscode from 'vscode';
import { assertIsolatedWorkspace } from '../support/workspaceGuard';
import { removePath, writeText } from '../support/originalApis';
import {
  activateExtension,
  artifactIds,
  assertDerivedCountsConsistent,
  converge,
  doc,
  folderByName,
  pollFor,
  refresh,
  showDiagnostics,
  sleep,
  WATCHER_WINDOW_MS,
  type ConvergePath,
  type ExtensionSeams,
} from '../support/helpers';

const level2: { label: string; path: ConvergePath }[] = [];

suite('MVP watchers без restart (Extension Host)', () => {
  let seams: ExtensionSeams;
  let valid: vscode.WorkspaceFolder;
  let degraded: vscode.WorkspaceFolder;

  suiteSetup(async () => {
    assertIsolatedWorkspace();
    seams = await activateExtension();
    valid = folderByName('mvp-valid');
    degraded = folderByName('mvp-degraded');
    // Watchers создаются при activation; даём им время стать ready и
    // убеждаемся, что предыдущий refresh (если был) завершён.
    await sleep(1500);
  });

  // Уровень 1: hard watcher-only asserts. Тест НЕ вызывает harnessNavigator.refresh
  // внутри измерения и не содержит fallback-ветки; таймаут = FAIL.
  test('artifact watcher: новый и изменённый STEP отражаются без refresh', async () => {
    const created = vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-720.md');
    const existing = vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-703.md');
    const originalExisting = await vscode.workspace.fs.readFile(existing);
    try {
      await writeText(created, doc('STEP-720', 'status: planned\n', 'Появился без refresh'));
      await pollFor(
        () => artifactIds(seams.getActiveArtifactSnapshot(valid)).includes('STEP-720'),
        `artifact watcher must publish STEP-720 within ${WATCHER_WINDOW_MS} ms`,
        WATCHER_WINDOW_MS,
      );
      assertDerivedCountsConsistent(seams);

      const before = seams.getStatusBarSnapshot()?.counts.active ?? 0;
      await writeText(
        existing,
        doc('STEP-703', 'status: in_progress\n', 'Запланированный шаг MVP'),
      );
      await pollFor(
        () => {
          const focus = seams.getFocusViewSnapshot().find((node) => node.label === 'mvp-valid');
          const active = focus?.children[0]?.children.map((item) => item.label) ?? [];
          return active.includes('STEP-703');
        },
        'artifact watcher must move STEP-703 to Focus View active group',
        WATCHER_WINDOW_MS,
      );
      await pollFor(
        () => seams.getStatusBarSnapshot()?.counts.active === before + 1,
        'status bar counts follow the watcher-driven status change',
        WATCHER_WINDOW_MS,
      );
      assertDerivedCountsConsistent(seams);
    } finally {
      await vscode.workspace.fs.writeFile(existing, originalExisting);
      await removePath(created);
      await sleep(500);
      await refresh();
    }
  });

  test('manifest watcher: исправление manifest переводит root invalid → valid и обратно', async () => {
    const invalid = folderByName('mvp-invalid-manifest');
    const manifest = vscode.Uri.joinPath(invalid.uri, '.harness/manifest.yaml');
    const original = await vscode.workspace.fs.readFile(manifest);
    const text = new TextDecoder().decode(original);
    assert.ok(text.includes('banana'));
    try {
      await writeText(manifest, text.replace('banana', '0.6.0'));
      await pollFor(
        () => seams.getActiveArtifactSnapshot(invalid) !== undefined,
        'manifest watcher must turn mvp-invalid-manifest into a valid root',
        WATCHER_WINDOW_MS,
      );
      const validReport = await showDiagnostics();
      assert.equal(
        validReport.states.find((state) => state.workspaceRoot === invalid.uri.fsPath)?.kind,
        'valid',
      );
      assertDerivedCountsConsistent(seams);

      await writeText(manifest, text);
      await pollFor(
        () => seams.getActiveArtifactSnapshot(invalid) === undefined,
        'manifest watcher must turn the root back into invalidManifest',
        WATCHER_WINDOW_MS,
      );
      const invalidReport = await showDiagnostics();
      assert.equal(
        invalidReport.states.find((state) => state.workspaceRoot === invalid.uri.fsPath)?.kind,
        'invalidManifest',
      );
      assertDerivedCountsConsistent(seams);
    } finally {
      await vscode.workspace.fs.writeFile(manifest, original);
    }
  });

  // Уровень 2: watcher-only окно, затем документированный refresh fallback (REQ-009).
  test('requirements STATUS.md projection обновляет lifecycle REQ', async () => {
    const status = vscode.Uri.joinPath(valid.uri, 'docs/requirements/STATUS.md');
    const original = await vscode.workspace.fs.readFile(status);
    const text = new TextDecoder().decode(original);
    const reqStatus = () =>
      seams.getActiveArtifactSnapshot(valid)?.artifacts.find((item) => item.id === 'REQ-701')
        ?.status;
    try {
      await writeText(status, text.replace('partial', 'completed'));
      const path = await converge(() => reqStatus() === 'completed', 'STATUS.md projection');
      assert.ok(path, 'REQ-701 lifecycle did not change through watcher or refresh');
      level2.push({ label: 'STATUS.md projection', path });
      assertDerivedCountsConsistent(seams);
    } finally {
      await vscode.workspace.fs.writeFile(status, original);
      await refresh();
    }
    assert.equal(reqStatus(), 'partial');
  });

  test('Harness-aware guide: references обновляются', async () => {
    const extra = vscode.Uri.joinPath(valid.uri, 'docs/guides/extra.md');
    const hasReference = () =>
      seams
        .getActiveArtifactSnapshot(valid)
        ?.references.some(
          (reference) => reference.targetId === 'STEP-703' && reference.file === extra.fsPath,
        ) === true;
    try {
      await writeText(extra, 'Новая ссылка на STEP-703.\n');
      const path = await converge(hasReference, 'guide references');
      assert.ok(path, 'guide references did not update through watcher or refresh');
      level2.push({ label: 'guide references', path });
      assertDerivedCountsConsistent(seams);
    } finally {
      await removePath(extra);
      await refresh();
    }
    assert.ok(!hasReference());
  });

  test('command graph: CommandGraphReadError → восстановление каталога', async () => {
    const graph = vscode.Uri.joinPath(degraded.uri, '.harness/command-transitions.json');
    const validGraph = await vscode.workspace.fs.readFile(
      vscode.Uri.joinPath(valid.uri, '.harness/command-transitions.json'),
    );
    const original = await vscode.workspace.fs.readFile(graph);
    const kind = () => seams.getCommandCatalogState(degraded)?.kind;
    const paths: ConvergePath[] = [];
    try {
      await writeText(graph, '{ malformed');
      const failing = await converge(() => kind() === 'readError', 'command graph readError');
      assert.ok(failing, 'catalog did not reach readError');
      paths.push(failing);
      const report = await showDiagnostics();
      assert.ok(report.lines.some((line) => line.includes('CommandGraphReadError')));

      await vscode.workspace.fs.writeFile(graph, validGraph);
      const recovered = await converge(() => kind() === 'ready', 'command graph recovery');
      assert.ok(recovered, 'catalog did not recover');
      paths.push(recovered);
      assertDerivedCountsConsistent(seams);
    } finally {
      await vscode.workspace.fs.writeFile(graph, original);
      await refresh();
    }
    assert.equal(kind(), 'unsupportedSchema');
    level2.push({
      label: 'command graph',
      path: paths.includes('refresh fallback') ? 'refresh fallback' : 'watcher',
    });
  });

  test('aggregate: среди сценариев уровня 2 не более одного refresh fallback', () => {
    console.log(`[level2] ${level2.map((item) => `${item.label}=${item.path}`).join('; ')}`);
    assert.equal(level2.length, 3, 'all level-2 scenarios must have run');
    const fallbacks = level2.filter((item) => item.path === 'refresh fallback');
    assert.ok(
      fallbacks.length <= 1,
      `watchers did not deliver events for ${fallbacks.map((item) => item.label).join(', ')}`,
    );
  });
});
