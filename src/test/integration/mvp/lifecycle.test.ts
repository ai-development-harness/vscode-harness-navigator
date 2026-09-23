import * as assert from 'node:assert/strict';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { assertIsolatedWorkspace } from '../support/workspaceGuard';
import { originalFs, removePath } from '../support/originalApis';
import {
  activateExtension,
  artifactIds,
  doc,
  mvpDirectory,
  pollFor,
  readSkipMarkers,
  showDiagnostics,
  sleep,
  type ExtensionSeams,
} from '../support/helpers';

const MANIFEST = [
  'harness:',
  '  version: "1"',
  '  release: "0.6.0"',
  'protocol:',
  '  taskDirectory: planning/tasks',
  'sources:',
  '  projectOverview: docs/PROJECT.md',
  '  requirements: docs/requirements',
  '  adrDirectory: docs/adr',
  '  architecture: docs/architecture.md',
  '  openQuestions: docs/open-questions',
  '  openQuestionsIndex: docs/OPEN_QUESTIONS.md',
  '  roadmap: planning/PLAN.md',
  '  status: planning/STATUS.md',
  '',
].join('\n');

function addRoot(root: string): Promise<vscode.WorkspaceFolder> {
  const uri = vscode.Uri.file(root);
  const count = vscode.workspace.workspaceFolders?.length ?? 0;
  const changed = new Promise<void>((resolve) => {
    const subscription = vscode.workspace.onDidChangeWorkspaceFolders(() => {
      subscription.dispose();
      resolve();
    });
  });
  assert.ok(vscode.workspace.updateWorkspaceFolders(count, 0, { uri }));
  return changed.then(() => {
    const folder = vscode.workspace.workspaceFolders?.find((item) => item.uri.fsPath === root);
    assert.ok(folder, 'added root must be present in workspaceFolders');
    return folder;
  });
}

function removeRoot(folder: vscode.WorkspaceFolder): Promise<void> {
  const changed = new Promise<void>((resolve) => {
    const subscription = vscode.workspace.onDidChangeWorkspaceFolders(() => {
      subscription.dispose();
      resolve();
    });
  });
  assert.ok(vscode.workspace.updateWorkspaceFolders(folder.index, 1));
  return changed;
}

suite('multi-root lifecycle без restart (Extension Host)', () => {
  let seams: ExtensionSeams;
  suiteSetup(async () => {
    assertIsolatedWorkspace();
    seams = await activateExtension();
  });

  test('добавление и удаление root обновляет state, index, views и status bar', async () => {
    const root = path.join(mvpDirectory(), 'mvp-added');
    originalFs.mkdirSync(path.join(root, '.harness'), { recursive: true });
    originalFs.mkdirSync(path.join(root, 'planning', 'tasks'), { recursive: true });
    originalFs.writeFileSync(path.join(root, '.harness', 'manifest.yaml'), MANIFEST);
    originalFs.writeFileSync(
      path.join(root, 'planning', 'tasks', 'STEP-771.md'),
      doc('STEP-771', 'status: in_progress\n', 'Добавленный root'),
    );
    const before = seams.getStatusBarSnapshot();
    assert.ok(before);
    let added: vscode.WorkspaceFolder | undefined;
    try {
      const otherFolder = vscode.workspace.workspaceFolders?.[0];
      assert.ok(otherFolder);
      const otherBefore = artifactIds(seams.getActiveArtifactSnapshot(otherFolder));

      added = await addRoot(root);
      await pollFor(
        () =>
          artifactIds(seams.getActiveArtifactSnapshot(added as vscode.WorkspaceFolder)).includes(
            'STEP-771',
          ),
        'index of the added root',
      );
      const report = await showDiagnostics();
      assert.ok(
        report.states.some((state) => state.workspaceRoot === root && state.kind === 'valid'),
        'added root must be detected as valid',
      );
      await pollFor(
        () => seams.getStatusBarSnapshot()?.counts.active === before.counts.active + 1,
        'status bar counts include the added root',
      );
      assert.ok(seams.getWatcherCount(added) > 0, 'added root must have live watchers');
      const afterAdd = seams.getStatusBarSnapshot();
      assert.ok(afterAdd?.visible);
      assert.ok(afterAdd.text.includes(`${before.counts.active + 1} `), afterAdd.text);
      assert.ok(afterAdd.tooltip.includes('mvp-added'), afterAdd.tooltip);
      assert.ok(seams.getSummaryViewSnapshot().some((node) => node.label === 'mvp-added'));
      assert.ok(seams.getFocusViewSnapshot().length > 0);
      assert.deepEqual(artifactIds(seams.getActiveArtifactSnapshot(otherFolder)), otherBefore);
      assert.ok(seams.getCommandCatalogState(added) !== undefined, 'catalog state for added root');

      const removed = added;
      await removeRoot(removed);
      added = undefined;
      await pollFor(
        () => seams.getActiveArtifactSnapshot(removed) === undefined,
        'index of the removed root is released',
      );
      await pollFor(
        () => seams.getStatusBarSnapshot()?.counts.active === before.counts.active,
        'status bar counts drop the removed root',
      );
      assert.equal(seams.getCommandCatalogState(removed), undefined);
      assert.equal(seams.getWatcherCount(removed), 0, 'watchers of the removed root are released');
      const afterRemove = seams.getStatusBarSnapshot();
      assert.equal(afterRemove?.visible, before.visible);
      assert.equal(afterRemove?.text, before.text);
      assert.ok(!afterRemove?.tooltip.includes('mvp-added'));
      assert.ok(!seams.getSummaryViewSnapshot().some((node) => node.label === 'mvp-added'));
      const afterReport = await showDiagnostics();
      assert.ok(!afterReport.states.some((state) => state.workspaceRoot === root));
      assert.ok(!afterReport.lines.some((line) => line.includes('mvp-added')));
      assert.deepEqual(artifactIds(seams.getActiveArtifactSnapshot(otherFolder)), otherBefore);

      // Watcher удалённого root больше не меняет state.
      originalFs.writeFileSync(
        path.join(root, 'planning', 'tasks', 'STEP-772.md'),
        doc('STEP-772', 'status: in_progress\n', 'После удаления root'),
      );
      await sleep(1500);
      assert.equal(seams.getActiveArtifactSnapshot(removed), undefined);
      assert.equal(seams.getStatusBarSnapshot()?.counts.active, before.counts.active);
    } finally {
      if (added !== undefined) await removeRoot(added);
      await removePath(vscode.Uri.file(root));
    }
  });

  test('два root с одинаковым basename дают уникальные id Summary view и различимый tooltip', async () => {
    const rootA = path.join(mvpDirectory(), 'dup-a', 'app');
    const rootB = path.join(mvpDirectory(), 'dup-b', 'app');
    for (const root of [rootA, rootB]) {
      originalFs.mkdirSync(path.join(root, '.harness'), { recursive: true });
      originalFs.mkdirSync(path.join(root, 'planning', 'tasks'), { recursive: true });
      originalFs.writeFileSync(path.join(root, '.harness', 'manifest.yaml'), MANIFEST);
    }
    const added: vscode.WorkspaceFolder[] = [];
    try {
      added.push(await addRoot(rootA));
      added.push(await addRoot(rootB));
      await pollFor(
        () => seams.getSummaryViewSnapshot().filter((node) => node.label === 'app').length === 2,
        'two same-named roots in Summary view',
      );
      const ids = seams
        .getSummaryViewSnapshot()
        .filter((node) => node.label === 'app')
        .map((node) => node.id);
      assert.ok(ids.every((id) => id !== undefined));
      assert.equal(new Set(ids).size, 2, `TreeItem ids must be unique: ${ids.join(', ')}`);
      const tooltip = seams.getStatusBarSnapshot()?.tooltip ?? '';
      assert.ok(tooltip.includes(added[0]?.uri.toString() ?? '?'), tooltip);
      assert.ok(tooltip.includes(added[1]?.uri.toString() ?? '?'), tooltip);
    } finally {
      for (const folder of [...added].reverse()) await removeRoot(folder);
      await removePath(vscode.Uri.file(path.dirname(rootA)));
      await removePath(vscode.Uri.file(path.dirname(rootB)));
    }
  });

  test('runtime-added containment root сразу получает ConfigurationBlocked', async function () {
    const markers = readSkipMarkers();
    const root = path.join(mvpDirectory(), 'mvp-added-symlink');
    originalFs.mkdirSync(path.join(root, '.harness'), { recursive: true });
    originalFs.mkdirSync(path.join(root, 'planning'), { recursive: true });
    originalFs.writeFileSync(path.join(root, '.harness', 'manifest.yaml'), MANIFEST);
    try {
      try {
        originalFs.symlinkSync(
          path.join('..', '..', 'mvp-external', 'planning', 'tasks'),
          path.join(root, 'planning', 'tasks'),
        );
      } catch (error) {
        const code = (error as NodeJS.ErrnoException).code;
        if (code === 'EPERM' || code === 'EACCES') {
          console.log(`symlink fixture unavailable (${code}); marker: ${JSON.stringify(markers)}`);
          return this.skip();
        }
        throw error;
      }
      const folder = await addRoot(root);
      try {
        await pollFor(async () => {
          const report = await showDiagnostics();
          const state = report.states.find((item) => item.workspaceRoot === root);
          return state?.kind === 'configurationBlocked';
        }, 'ConfigurationBlocked for the runtime-added symlink root');
        const report = await showDiagnostics();
        const state = report.states.find((item) => item.workspaceRoot === root);
        assert.equal(state?.diagnostic.category, 'ConfigurationBlocked');
        assert.equal(seams.getActiveArtifactSnapshot(folder), undefined);
        assert.ok(!artifactIds(seams.getActiveArtifactSnapshot(folder)).includes('STEP-990'));
      } finally {
        await removeRoot(folder);
      }
    } finally {
      await removePath(vscode.Uri.file(root));
    }
  });

  test('activate → deactivate → activate сохраняет registeredDisposableCount с новыми подписками', async () => {
    const before = seams.getActiveRegistrationCount();
    assert.ok(before > 0);
    seams.deactivate();
    assert.equal(seams.getActiveRegistrationCount(), 0);
    seams.deactivate();
    seams.activate({ subscriptions: [] } as unknown as vscode.ExtensionContext);
    assert.equal(seams.getActiveRegistrationCount(), before);
    seams.deactivate();
    seams.activate({ subscriptions: [] } as unknown as vscode.ExtensionContext);
    assert.equal(seams.getActiveRegistrationCount(), before);
    // Расширение остаётся рабочим для следующих suites: watchers пересозданы, даём им время.
    await sleep(2000);
    const status = seams.getStatusBarSnapshot();
    assert.ok(status?.visible);
  });
});
