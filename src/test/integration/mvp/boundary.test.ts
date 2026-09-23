import * as assert from 'node:assert/strict';
import * as childProcess from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { assertIsolatedWorkspace } from '../support/workspaceGuard';
import { originalFs, writeText, removePath } from '../support/originalApis';
import { BoundarySpies } from '../support/boundarySpies';
import { hashRoots } from '../support/treeHash';
import {
  activateExtension,
  artifactIds,
  doc,
  extensionPath,
  folderByName,
  pollFor,
  pollUntil,
  positionOf,
  refresh,
  showDiagnostics,
  stubQuickPick,
  type ExtensionSeams,
} from '../support/helpers';

const CORE_FORBIDDEN = [
  'child_process.spawn',
  'child_process.execFileSync',
  'fs.writeFileSync',
  'vscode.window.createTerminal',
];

suite('boundary: offline, no-shell, no-auth, no-mutation (Extension Host)', () => {
  let seams: ExtensionSeams;
  let valid: vscode.WorkspaceFolder;
  let spies: BoundarySpies;
  let restoreQuickPick: (() => void) | undefined;
  let quickPickChoice: (items: readonly vscode.QuickPickItem[]) => unknown = () => undefined;
  let offered: () => readonly vscode.QuickPickItem[] = () => [];
  let terminalsBaseline = 0;

  suiteSetup(async () => {
    assertIsolatedWorkspace();
    seams = await activateExtension();
    valid = folderByName('mvp-valid');
    // Stub showQuickPick устанавливается ДО spies: spy оборачивает stub, а
    // реальный UI (блокирующий тест) не открывается.
    const stub = stubQuickPick((items) => quickPickChoice(items));
    restoreQuickPick = stub.restore;
    offered = stub.offered;
    spies = new BoundarySpies();
    spies.install(path.join(extensionPath(), 'dist', 'extension.js'));
  });

  suiteTeardown(async () => {
    spies.restore();
    restoreQuickPick?.();
    await refresh();
  });

  test('controls: negative — forbidden API из test-кода проходит call-through без sentinel', async () => {
    spies.reset();
    const terminalsBeforeControl = vscode.window.terminals.length;
    const output = childProcess.execFileSync(process.execPath, [
      '-e',
      'process.stdout.write("ok")',
    ]);
    assert.equal(output.toString(), 'ok', 'call-through must execute the original API');
    const terminal = vscode.window.createTerminal({ name: 'boundary-control' });
    terminal.dispose();
    // Control-терминал закрывается сразу; baseline снимается после его исчезновения.
    await pollUntil(() => vscode.window.terminals.length === terminalsBeforeControl, 5000);
    const execRecords = spies.recordsFor('child_process.execFileSync');
    assert.ok(execRecords.length >= 1, 'execFileSync from test code must be recorded');
    assert.ok(execRecords.every((record) => !record.extensionOriginated && !record.sentinel));
    const terminalRecords = spies.recordsFor('vscode.window.createTerminal');
    assert.ok(terminalRecords.length >= 1);
    assert.ok(terminalRecords.every((record) => !record.extensionOriginated && !record.sentinel));
    // Имитированный stack без кадра bundle не атрибутируется расширению.
    assert.equal(spies.classifyStack('Error\n    at fn (/other/place/file.js:1:1)'), false);
    assert.equal(
      spies.classifyStack(
        `Error\n    at fn (${path.join(extensionPath(), 'dist', 'extension.js')}:1:1)`,
      ),
      true,
    );
    assert.equal(spies.violations().length, 0);
    console.log(
      `[boundary controls] negative: ${spies.records.length} records, violations=0, unpatched=${JSON.stringify(spies.unpatched)}`,
    );
    // vscode.workspace.fs — non-configurable свойства Extension Host: runtime-перехват
    // невозможен. Эти API покрывает только статическая проверка bundle `yarn inspect:package`
    // (запрет токена workspace.fs); во время выполнения они не отслеживаются.
    for (const item of spies.unpatched)
      assert.ok(
        item.api.startsWith('vscode.workspace.fs.'),
        `unexpected non-interceptable API ${item.api}: ${item.reason}`,
      );
    for (const api of CORE_FORBIDDEN)
      assert.ok(
        !spies.unpatched.some((item) => item.api === api),
        `core forbidden API ${api} could not be intercepted`,
      );
    // Baseline terminals снимается после control-фазы.
    terminalsBaseline = vscode.window.terminals.length;
  });

  test('controls: собственная запись теста через сохранённый оригинал не попадает в recorder', () => {
    // vscode.workspace.fs не перехватывается (unpatched), поэтому проверка выполняется на node:fs.
    const file = path.join(valid.uri.fsPath, 'docs/guides/control.md');
    const before = spies.recordsFor('fs.writeFileSync').length;
    try {
      originalFs.writeFileSync(file, 'control\n');
    } finally {
      originalFs.rmSync(file, { force: true });
    }
    assert.equal(spies.recordsFor('fs.writeFileSync').length, before);
    // Контраст: тот же вызов через перехваченный fs записывается, но не из bundle.
    try {
      fs.writeFileSync(file, 'control\n');
    } finally {
      originalFs.rmSync(file, { force: true });
    }
    const records = spies.recordsFor('fs.writeFileSync');
    assert.equal(records.length, before + 1);
    assert.equal(records[records.length - 1]?.extensionOriginated, false);
    assert.equal(spies.violations().length, 0);
  });

  test('controls: positive — observed spies видят вызовы bundle во время Refresh и Go to Artifact', async () => {
    spies.reset();
    await refresh();
    const fsRecords = spies.records.filter(
      (record) => record.api === 'fs.openSync' || record.api === 'fs.readFileSync',
    );
    const fromBundle = fsRecords.filter((record) => record.extensionOriginated);
    assert.ok(
      fromBundle.length >= 1,
      'spies do not see bundle fs reads during refresh: boundary suite cannot give PASS',
    );
    quickPickChoice = (items) => items.find((item) => item.label === 'STEP-703');
    await vscode.commands.executeCommand('harnessNavigator.goToArtifact');
    const quickPick = spies.recordsFor('vscode.window.showQuickPick');
    assert.ok(
      quickPick.some((record) => record.extensionOriginated),
      'spies do not see bundle showQuickPick during Go to Artifact',
    );
    console.log(
      `[boundary controls] positive: fs.openSync/readFileSync from bundle=${fromBundle.length}, showQuickPick from bundle=${quickPick.filter((record) => record.extensionOriginated).length}`,
    );
  });

  test('controls: violation-path — bundle-вызов эскалированного API фиксируется как нарушение и завершается sentinel', async () => {
    spies.reset();
    spies.escalatedApis = new Set(['fs.openSync', 'fs.readFileSync']);
    try {
      await refresh();
    } finally {
      spies.escalatedApis = new Set();
    }
    const violations = spies.records.filter(
      (record) => record.kind === 'forbidden' && record.extensionOriginated && record.sentinel,
    );
    assert.ok(violations.length >= 1, 'recorder must capture a bundle violation');
    console.log(`[boundary controls] violation-path: ${violations.length} sentinel violations`);
    // Восстанавливающий refresh ДО основной части: derived state не должен остаться испорченным.
    spies.reset();
    await refresh();
    assert.ok(artifactIds(seams.getActiveArtifactSnapshot(valid)).includes('STEP-701'));
    assert.equal(spies.violations().length, 0);
    spies.reset();
  });

  test('flows под spies: ноль нарушений, terminals не растут, Harness файлы не изменены', async () => {
    const roots = (vscode.workspace.workspaceFolders ?? []).map((folder) => folder.uri.fsPath);
    const hashesBefore = hashRoots(roots);
    const terminalsBefore = vscode.window.terminals.length;
    assert.equal(terminalsBefore, terminalsBaseline, 'control terminal must be closed');
    spies.reset();

    await refresh();
    await showDiagnostics();
    seams.getArtifactsViewSnapshot();
    seams.getFocusViewSnapshot();
    seams.getSummaryViewSnapshot();
    seams.getStatusBarSnapshot();
    seams.getCommandsViewSnapshot();

    quickPickChoice = (items) => items.find((item) => item.label === 'STEP-702');
    await vscode.commands.executeCommand('harnessNavigator.goToArtifact');
    quickPickChoice = (items) => items.find((item) => item.label === 'STEP LIST');
    await vscode.commands.executeCommand('harnessNavigator.findCommand');
    const commandNode = seams.getCommandsViewCommandNodes()[0];
    await vscode.commands.executeCommand('harnessNavigator.copyCommand', commandNode);

    const guide = vscode.Uri.joinPath(valid.uri, 'docs/guides/guide.md');
    const document = await vscode.workspace.openTextDocument(guide);
    await vscode.window.showTextDocument(document);
    const onReq = positionOf(document, 'REQ-701');
    // In-memory lookups: после открытия документа hover/completion/definition/references
    // не должны читать fs из bundle (REQ-009: без повторного scanning).
    const readsBefore = spies.records.filter(
      (record) =>
        record.kind === 'observed' && record.api.startsWith('fs.') && record.extensionOriginated,
    ).length;
    await vscode.commands.executeCommand('vscode.executeDefinitionProvider', guide, onReq);
    await vscode.commands.executeCommand('vscode.executeHoverProvider', guide, onReq);
    await vscode.commands.executeCommand(
      'vscode.executeCompletionItemProvider',
      guide,
      positionOf(document, 'STEP-701', 5),
    );
    const references = await vscode.commands.executeCommand<vscode.Location[]>(
      'vscode.executeReferenceProvider',
      guide,
      onReq,
    );
    assert.ok(references.length > 0);
    const readsAfter = spies.records.filter(
      (record) =>
        record.kind === 'observed' && record.api.startsWith('fs.') && record.extensionOriginated,
    ).length;
    assert.equal(readsAfter, readsBefore, 'lookups must be served from in-memory indexes');

    const reqArtifact = seams
      .getActiveArtifactSnapshot(valid)
      ?.artifacts.find((artifact) => artifact.id === 'REQ-701');
    quickPickChoice = (items) => items.find((item) => item.label === 'STEP-702');
    await vscode.commands.executeCommand('harnessNavigator.showRelations', {
      artifact: reqArtifact,
      folder: valid,
    });
    assert.ok(offered().length > 0);
    await vscode.commands.executeCommand('harnessNavigator.findAllReferences', {
      artifact: reqArtifact,
      folder: valid,
    });

    // Watcher-изменение: собственные записи теста идут через сохранённые оригиналы.
    const changed = vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-730.md');
    try {
      await writeText(changed, doc('STEP-730', 'status: planned\n', 'Под spies'));
      await pollFor(
        () => artifactIds(seams.getActiveArtifactSnapshot(valid)).includes('STEP-730'),
        'watcher change observed under spies',
      );
    } finally {
      await removePath(changed);
    }
    await pollFor(
      () => !artifactIds(seams.getActiveArtifactSnapshot(valid)).includes('STEP-730'),
      'watcher removal observed under spies',
    );

    const violations = spies.violations();
    assert.deepEqual(
      violations,
      [],
      `extension-originated forbidden calls: ${violations.map((item) => item.api).join(', ')}`,
    );
    assert.equal(vscode.window.terminals.length, terminalsBefore);
    assert.deepEqual(hashRoots(roots), hashesBefore, 'Harness files must be unchanged after flows');
    const observedFs = spies.records.filter(
      (record) =>
        record.kind === 'observed' && record.api.startsWith('fs.') && record.extensionOriginated,
    ).length;
    console.log(
      `[boundary] records=${spies.records.length}, extension fs reads=${observedFs}, unpatched=${JSON.stringify(spies.unpatched)}`,
    );
  });
});
