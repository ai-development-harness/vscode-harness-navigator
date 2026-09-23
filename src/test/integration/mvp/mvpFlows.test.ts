import * as assert from 'node:assert/strict';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { assertIsolatedWorkspace } from '../support/workspaceGuard';
import { originalFs, removePath, writeText } from '../support/originalApis';
import { hashRoots } from '../support/treeHash';
import { assertNoExternalContent } from '../support/externalContent';
import {
  activateExtension,
  artifactIds,
  assertDerivedCountsConsistent,
  doc,
  flatten,
  folderByName,
  isRussian,
  pollFor,
  positionOf,
  readSkipMarkers,
  refresh,
  showDiagnostics,
  sleep,
  stubQuickPick,
  textOfHover,
  type DiagnosticsReportLike,
  type ExtensionSeams,
} from '../support/helpers';

interface DetectionCase {
  readonly name: string;
  readonly kind: string;
  readonly category: string;
  readonly en?: string;
  readonly ru?: string;
  /** Ключ маркера prepare-test-workspace, если OS может отказать в создании fixture. */
  readonly marker?: string;
}

const DETECTION: readonly DetectionCase[] = [
  { name: 'mvp-valid', kind: 'valid', category: 'ValidHarnessProject' },
  { name: 'mvp-degraded', kind: 'valid', category: 'ValidHarnessProject' },
  {
    name: 'mvp-ordinary',
    kind: 'nonHarness',
    category: 'NotHarnessProject',
    en: 'Harness manifest is absent.',
    ru: 'Manifest Harness отсутствует.',
  },
  {
    name: 'mvp-invalid-manifest',
    kind: 'invalidManifest',
    category: 'InvalidManifest',
    en: 'Harness manifest contains an invalid release: banana.',
    ru: 'Manifest Harness содержит некорректную версию release: banana.',
  },
  {
    name: 'mvp-old-release',
    kind: 'unsupportedVersion',
    category: 'UnsupportedHarnessVersion',
    en: 'Harness release is not supported: 0.5.0.',
    ru: 'Версия Harness не поддерживается: 0.5.0.',
  },
  {
    name: 'mvp-unsupported-schema',
    kind: 'unsupportedSchema',
    category: 'UnsupportedSchema',
    en: 'Harness manifest schema is not supported: 2.',
    ru: 'Schema manifest Harness не поддерживается: 2.',
  },
  {
    name: 'mvp-traversal',
    kind: 'configurationBlocked',
    category: 'ConfigurationBlocked',
    en: 'A configured path is blocked by workspace containment.',
    ru: 'Настроенный путь заблокирован границей workspace.',
  },
  {
    name: 'mvp-absolute',
    kind: 'configurationBlocked',
    category: 'ConfigurationBlocked',
    en: 'A configured path is blocked by workspace containment.',
    ru: 'Настроенный путь заблокирован границей workspace.',
  },
  {
    name: 'mvp-symlink',
    kind: 'configurationBlocked',
    category: 'ConfigurationBlocked',
    en: 'A configured path is blocked by workspace containment.',
    ru: 'Настроенный путь заблокирован границей workspace.',
    marker: 'mvp-symlink',
  },
  {
    name: 'mvp-manifest-symlink',
    kind: 'configurationBlocked',
    category: 'ConfigurationBlocked',
    en: 'Manifest resolves outside of the workspace root.',
    ru: 'Manifest разрешается за пределы корня workspace.',
    marker: 'mvp-manifest-symlink',
  },
  {
    name: 'mvp-unreadable',
    kind: 'configurationBlocked',
    category: 'UnexpectedInternalError',
    marker: 'mvp-unreadable',
  },
];

const CONTAINMENT = ['mvp-traversal', 'mvp-absolute', 'mvp-symlink', 'mvp-manifest-symlink'];

suite('MVP flows (Extension Host)', () => {
  let seams: ExtensionSeams;
  let valid: vscode.WorkspaceFolder;
  let degraded: vscode.WorkspaceFolder;
  let guide: vscode.Uri;
  let restoreQuickPick: (() => void) | undefined;

  suiteSetup(async () => {
    assertIsolatedWorkspace();
    seams = await activateExtension();
    valid = folderByName('mvp-valid');
    degraded = folderByName('mvp-degraded');
    guide = vscode.Uri.joinPath(valid.uri, 'docs/guides/guide.md');
  });

  teardown(() => {
    restoreQuickPick?.();
    restoreQuickPick = undefined;
  });

  test('detection states: каждый mvp root даёт ожидаемые kind, category и локализованное объяснение', async () => {
    const markers = readSkipMarkers();
    const report = await showDiagnostics();
    assert.equal(report.states.length, vscode.workspace.workspaceFolders?.length);
    assert.equal(
      report.summary,
      isRussian()
        ? `Harness Navigator: проверено корней workspace: ${report.states.length}.`
        : `Harness Navigator diagnostics: ${report.states.length} workspace roots inspected.`,
    );
    for (const expected of DETECTION) {
      const folder = folderByName(expected.name);
      const state = report.states.find((item) => item.workspaceRoot === folder.uri.fsPath);
      assert.ok(state, `${expected.name}: state is missing`);
      const skipReason = expected.marker === undefined ? undefined : markers[expected.marker];
      if (skipReason !== undefined) {
        console.log(`[skip] ${expected.name}: ${skipReason}`);
        continue;
      }
      // mvp-valid достигает kind valid безусловно на любой platform (ADR-007 §3).
      assert.equal(state.kind, expected.kind, `${expected.name}: kind`);
      assert.equal(state.diagnostic.category, expected.category, `${expected.name}: category`);
      const explanation = isRussian() ? expected.ru : expected.en;
      if (explanation !== undefined)
        assert.ok(
          report.lines.some((line) =>
            line.startsWith(`${folder.uri.fsPath}: ${expected.category} — ${explanation}`),
          ),
          `${expected.name}: localized line "${explanation}" is missing`,
        );
    }
    const old = report.states.find(
      (item) => item.workspaceRoot === folderByName('mvp-old-release').uri.fsPath,
    );
    assert.equal(old?.detectedRelease, '0.5.0');
    assert.equal(old?.minimumRelease, '0.6.0');
  });

  test('containment e2e: traversal, absolute, symlink и manifest-symlink блокируются на каждой platform', async function () {
    const markers = readSkipMarkers();
    const report = await showDiagnostics();
    const skipped: string[] = [];
    for (const name of CONTAINMENT) {
      const reason = markers[name];
      if (reason !== undefined) {
        skipped.push(`${name}: ${reason}`);
        continue;
      }
      const folder = folderByName(name);
      const state = report.states.find((item) => item.workspaceRoot === folder.uri.fsPath);
      // Без ветки по process.platform: ожидание одинаково на Linux/macOS/Windows.
      assert.equal(state?.kind, 'configurationBlocked', `${name}: kind`);
      assert.equal(state.diagnostic.category, 'ConfigurationBlocked', `${name}: category`);
      assert.equal(seams.getActiveArtifactSnapshot(folder), undefined, `${name}: no index`);
    }
    await assertNoExternalContent(seams, valid);

    // Symlink-файл STEP-991.md внутри valid root не индексируется, root остаётся valid.
    const markerLink = markers['mvp-valid-symlink-file'];
    const ids = artifactIds(seams.getActiveArtifactSnapshot(valid));
    assert.deepEqual(ids, ['ADR-701', 'OQ-701', 'REQ-701', 'STEP-701', 'STEP-702', 'STEP-703']);
    if (markerLink === undefined)
      assert.ok(
        originalFs
          .lstatSync(path.join(valid.uri.fsPath, 'planning/tasks/STEP-991.md'))
          .isSymbolicLink(),
        'STEP-991.md must be a static symlink fixture',
      );
    assert.ok(!ids.includes('STEP-991'));
    if (skipped.length > 0) {
      console.log(`[skip] containment fixtures not created by the OS: ${skipped.join('; ')}`);
      // Частичный пропуск не считается полным PASS: assert остальных фикстур выполнены выше.
      this.skip();
    }
  });

  test('complete taxonomy: все 12 категорий REQ-008 наблюдаются через Harness: Show Diagnostics', async function () {
    const markers = readSkipMarkers();
    const catalogPath = vscode.Uri.joinPath(degraded.uri, '.harness/command-transitions.json');
    const original = await vscode.workspace.fs.readFile(catalogPath);
    const observed = new Set<string>();
    const collect = (report: DiagnosticsReportLike) => {
      for (const state of report.states) observed.add(state.diagnostic.category);
      for (const line of report.lines) {
        const match = /: ([A-Za-z]+) — /u.exec(line);
        if (match?.[1] !== undefined) observed.add(match[1]);
      }
    };
    try {
      collect(await showDiagnostics());
      // CommandGraphReadError достигается runtime-переходом (malformed JSON) и восстанавливается.
      await writeText(catalogPath, '{ malformed');
      await refresh();
      await pollFor(
        () => seams.getCommandCatalogState(degraded)?.kind === 'readError',
        'degraded catalog readError',
      );
      collect(await showDiagnostics());
    } finally {
      await vscode.workspace.fs.writeFile(catalogPath, original);
      await refresh();
    }
    await pollFor(
      () => seams.getCommandCatalogState(degraded)?.kind === 'unsupportedSchema',
      'degraded catalog restored',
    );
    const required = [
      'NotHarnessProject',
      'InvalidManifest',
      'UnsupportedHarnessVersion',
      'UnsupportedSchema',
      'ArtifactDirectoryMissing',
      'ArtifactParseError',
      'DuplicateArtifactId',
      'InvalidArtifactReference',
      'ProjectionReadError',
      'CommandGraphReadError',
      'CommandGraphUnsupportedSchema',
      'UnexpectedInternalError',
    ];
    const missing = required.filter((category) => !observed.has(category));
    // Сначала утверждаем все достижимые категории; пропускается только UnexpectedInternalError.
    const unreachable = markers['mvp-unreadable'] !== undefined ? ['UnexpectedInternalError'] : [];
    const mustObserve = missing.filter((category) => !unreachable.includes(category));
    assert.deepEqual(
      mustObserve,
      [],
      `taxonomy categories not observed: ${mustObserve.join(', ')}`,
    );
    if (missing.length > 0 && unreachable.length > 0) {
      console.log(
        `[skip] UnexpectedInternalError not reachable: ${markers['mvp-unreadable']}; covered by unit tests manifestService.test.ts`,
      );
    }
    // Ни одна категория вне REQ-008/технического контракта не появляется.
    const known = new Set([...required, 'ValidHarnessProject', 'ConfigurationBlocked']);
    for (const category of observed) assert.ok(known.has(category), `unknown category ${category}`);
    if (unreachable.length > 0) this.skip();
  });

  test('views/providers/catalog smoke на mvp-valid', async () => {
    // Artifacts View: группы STEP/REQ/ADR/OQ c ID/title.
    const root = seams.getArtifactsViewSnapshot().find((node) => node.label === 'mvp-valid');
    assert.ok(root, 'Artifacts View root for mvp-valid');
    assert.deepEqual(
      root.children.map((group) => group.label),
      ['STEP', 'REQ', 'ADR', 'OQ'],
    );
    const step = root.children[0]?.children.find((item) => item.label === 'STEP-701');
    assert.equal(step?.description, 'Активный шаг MVP');
    assert.equal(
      step?.resourceFsPath,
      vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-701.md').fsPath,
    );
    assert.deepEqual(
      root.children[0]?.children.map((item) => item.label),
      ['STEP-701', 'STEP-702', 'STEP-703'],
    );
    // REQ lifecycle берётся из STATUS.md projection, а не из frontmatter (draft).
    assert.equal(
      seams
        .getActiveArtifactSnapshot(valid)
        ?.artifacts.find((artifact) => artifact.id === 'REQ-701')?.status,
      'partial',
    );

    // Focus View: active/blocked/open OQ.
    const focus = seams.getFocusViewSnapshot().find((node) => node.label === 'mvp-valid');
    assert.ok(focus);
    const groupIds = focus.children.map((group) => group.children.map((item) => item.label));
    assert.deepEqual(groupIds, [['STEP-701'], ['STEP-702'], ['OQ-701']]);

    // Go to Artifact открывает canonical файл.
    const picker = stubQuickPick((items) => items.find((item) => item.label === 'STEP-703'));
    restoreQuickPick = picker.restore;
    await vscode.commands.executeCommand('harnessNavigator.goToArtifact');
    assert.equal(
      vscode.window.activeTextEditor?.document.uri.fsPath,
      vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-703.md').fsPath,
    );
    picker.restore();

    // Providers в Harness-aware guide.
    const document = await vscode.workspace.openTextDocument(guide);
    await vscode.window.showTextDocument(document);
    const onReq = positionOf(document, 'REQ-701');
    const definitions = await vscode.commands.executeCommand<
      (vscode.Location | vscode.LocationLink)[]
    >('vscode.executeDefinitionProvider', guide, onReq);
    const first = definitions[0];
    assert.ok(first);
    assert.equal(
      ('targetUri' in first ? first.targetUri : first.uri).fsPath,
      vscode.Uri.joinPath(valid.uri, 'docs/requirements/REQ-701-mvp.md').fsPath,
    );
    const hover = textOfHover(
      await vscode.commands.executeCommand<vscode.Hover[]>(
        'vscode.executeHoverProvider',
        guide,
        onReq,
      ),
    );
    assert.ok(hover.includes('REQ-701'));
    assert.ok(hover.includes(isRussian() ? 'Тип: REQ' : 'Kind: REQ'));
    const completions = await vscode.commands.executeCommand<vscode.CompletionList>(
      'vscode.executeCompletionItemProvider',
      guide,
      positionOf(document, 'STEP-701', 5),
    );
    assert.ok(completions.items.some((item) => item.insertText === 'STEP-701'));
    const links = await vscode.commands.executeCommand<vscode.DocumentLink[]>(
      'vscode.executeLinkProvider',
      guide,
    );
    assert.ok(
      links.some(
        (link) =>
          link.target?.fsPath ===
          vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-701.md').fsPath,
      ),
    );
    const references = await vscode.commands.executeCommand<vscode.Location[]>(
      'vscode.executeReferenceProvider',
      guide,
      onReq,
    );
    const referenceFiles = references.map((location) => location.uri.fsPath);
    assert.ok(referenceFiles.includes(guide.fsPath));
    assert.ok(referenceFiles.some((file) => file.endsWith('STEP-701.md')));
    assert.ok(referenceFiles.every((file) => !file.includes(`${path.sep}node_modules${path.sep}`)));

    // Show Relations: клик по relation открывает файл.
    const reqArtifact = seams
      .getActiveArtifactSnapshot(valid)
      ?.artifacts.find((artifact) => artifact.id === 'REQ-701');
    assert.ok(reqArtifact);
    const relations = stubQuickPick((items) => items.find((item) => item.label === 'STEP-702'));
    restoreQuickPick = relations.restore;
    await vscode.commands.executeCommand('harnessNavigator.showRelations', {
      artifact: reqArtifact,
      folder: valid,
    });
    assert.ok(relations.offered().some((item) => item.label === 'STEP-702'));
    assert.equal(
      vscode.window.activeTextEditor?.document.uri.fsPath,
      vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-702.md').fsPath,
    );
    relations.restore();

    // Commands View: домены графа, Copy/Find Command только в clipboard.
    const commandsRoot = seams.getCommandsViewSnapshot().find((node) => node.label === 'mvp-valid');
    assert.ok(commandsRoot, 'Commands View root for mvp-valid');
    const domains = commandsRoot.children.map((node) => node.label);
    assert.ok(
      domains.includes('STEP') && domains.includes('PROJECT'),
      `domains: ${domains.join()}`,
    );
    assert.ok(flatten(commandsRoot.children).every((node) => node.hasCommand !== true));
    const terminalsBefore = vscode.window.terminals.length;
    const commandNode = seams
      .getCommandsViewCommandNodes()
      .find(
        (node) =>
          (node as { command?: { canonical?: string } }).command?.canonical ===
          'STEP PLAN STEP-NNN',
      );
    assert.ok(commandNode, 'STEP PLAN STEP-NNN node');
    await vscode.env.clipboard.writeText('sentinel');
    await vscode.commands.executeCommand('harnessNavigator.copyCommand', commandNode);
    assert.equal(await vscode.env.clipboard.readText(), 'STEP PLAN STEP-NNN');
    const finder = stubQuickPick((items) => items.find((item) => item.label === 'STEP LIST'));
    restoreQuickPick = finder.restore;
    await vscode.commands.executeCommand('harnessNavigator.findCommand');
    assert.equal(await vscode.env.clipboard.readText(), 'STEP LIST');
    finder.restore();
    assert.equal(vscode.window.terminals.length, terminalsBefore);
  });

  test('Status Bar и Summary отражают derived counts и открывают Harness View', async () => {
    assertDerivedCountsConsistent(seams);
    const status = seams.getStatusBarSnapshot();
    assert.ok(status);
    assert.ok(status.tooltip.includes('mvp-valid'));
    // Non-valid Harness root получает строку с категорией; NotHarnessProject в tooltip не попадает.
    assert.ok(status.tooltip.includes('mvp-invalid-manifest: InvalidManifest'), status.tooltip);
    assert.ok(!status.tooltip.includes('mvp-ordinary'), status.tooltip);
    // Click по item = навигация UI, а не dispatch Harness-команды.
    await vscode.commands.executeCommand(status.command ?? '');
    // Non-valid root показывает stable category и локализованное объяснение.
    const ordinary = seams.getSummaryViewSnapshot().find((node) => node.label === 'mvp-ordinary');
    assert.equal(ordinary?.children[0]?.label, 'NotHarnessProject');
    assert.equal(
      ordinary?.children[0]?.description,
      isRussian() ? 'Manifest Harness отсутствует.' : 'Harness manifest is absent.',
    );
    const validGroup = seams.getSummaryViewSnapshot().find((node) => node.label === 'mvp-valid');
    assert.equal(
      validGroup?.children.find(
        (child) => child.label === (isRussian() ? 'Релиз Harness' : 'Harness release'),
      )?.description,
      '0.6.0',
    );
    assert.ok(flatten(seams.getSummaryViewSnapshot()).every((node) => node.hasCommand !== true));
  });

  test('Harness: Refresh обновляет state сразу после команды и не меняет Harness файлы', async () => {
    const roots = (vscode.workspace.workspaceFolders ?? []).map((folder) => folder.uri.fsPath);
    const extra = vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-704.md');
    try {
      await writeText(extra, doc('STEP-704', 'status: in_progress\n', 'Refresh без watcher'));
      const before = hashRoots(roots);
      await refresh();
      // Без poll: snapshot обязан быть готов сразу после завершения команды.
      assert.ok(artifactIds(seams.getActiveArtifactSnapshot(valid)).includes('STEP-704'));
      assertDerivedCountsConsistent(seams);
      const report = await showDiagnostics();
      assert.ok(report.states.length > 0);
      assert.deepEqual(
        hashRoots(roots),
        before,
        'refresh/showDiagnostics must not mutate Harness files',
      );
    } finally {
      await removePath(extra);
      await refresh();
    }
    assert.ok(!artifactIds(seams.getActiveArtifactSnapshot(valid)).includes('STEP-704'));
  });

  test('cross-root isolation: одинаковый ID резолвится в файл своего root, diagnostics не пересекаются', async () => {
    const stepFor = (folder: vscode.WorkspaceFolder) =>
      vscode.Uri.joinPath(folder.uri, 'planning/tasks/STEP-705.md');
    const guideFor = (folder: vscode.WorkspaceFolder) =>
      vscode.Uri.joinPath(folder.uri, 'docs/guides/iso.md');
    const created = [stepFor(valid), guideFor(valid), stepFor(degraded), guideFor(degraded)];
    try {
      for (const folder of [valid, degraded]) {
        await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(folder.uri, 'docs/guides'));
        await writeText(stepFor(folder), doc('STEP-705', 'status: planned\n', 'Общий ID'));
        await writeText(guideFor(folder), 'Ссылка на STEP-705 в своём root.\n');
      }
      await refresh();
      for (const folder of [valid, degraded]) {
        const uri = guideFor(folder);
        const document = await vscode.workspace.openTextDocument(uri);
        await vscode.window.showTextDocument(document);
        const definitions = await vscode.commands.executeCommand<
          (vscode.Location | vscode.LocationLink)[]
        >('vscode.executeDefinitionProvider', uri, positionOf(document, 'STEP-705'));
        const target = definitions[0];
        assert.ok(target, `${folder.name}: definition`);
        assert.equal(
          ('targetUri' in target ? target.targetUri : target.uri).fsPath,
          stepFor(folder).fsPath,
        );
      }
      const report = await showDiagnostics();
      const degradedCategories = [
        'ArtifactParseError',
        'DuplicateArtifactId',
        'ProjectionReadError',
        'ArtifactDirectoryMissing',
        'CommandGraphUnsupportedSchema',
      ];
      for (const line of report.lines.filter((item) => item.includes('mvp-valid')))
        for (const category of degradedCategories)
          assert.ok(!line.includes(category), `mvp-valid line leaked ${category}: ${line}`);
      // blocked root не блокирует соседей.
      assert.ok(seams.getActiveArtifactSnapshot(valid) !== undefined);
      assert.ok(seams.getActiveArtifactSnapshot(degraded) !== undefined);
      assert.ok(artifactIds(seams.getActiveArtifactSnapshot(valid)).includes('STEP-701'));
      assert.ok(
        (seams.getActiveArtifactSnapshot(degraded)?.diagnostics.length ?? 0) > 0,
        'degraded root keeps its own diagnostics',
      );
    } finally {
      for (const uri of created) await removePath(uri);
      await removePath(vscode.Uri.joinPath(degraded.uri, 'docs/guides'));
      await vscode.commands.executeCommand('workbench.action.closeAllEditors');
      await refresh();
    }
  });

  test('node_modules не сканируется: ни references, ни artifacts, ни diagnostics', async () => {
    const snapshot = seams.getActiveArtifactSnapshot(valid);
    assert.ok(snapshot);
    assert.ok(!artifactIds(snapshot).includes('STEP-799'));
    assert.ok(
      snapshot.artifacts.every(
        (artifact) => !artifact.file.includes(`${path.sep}node_modules${path.sep}`),
      ),
    );
    const references = await vscode.commands.executeCommand<vscode.Location[]>(
      'vscode.executeReferenceProvider',
      guide,
      positionOf(await vscode.workspace.openTextDocument(guide), 'STEP-701'),
    );
    assert.ok(references.length > 0);
    assert.ok(references.every((location) => !location.uri.fsPath.includes('node_modules')));
    const report = await showDiagnostics();
    assert.ok(
      !report.lines.some((line) => line.includes('STEP-798')),
      'node_modules mention leaked',
    );
    const diagnosticsBefore = snapshot.diagnostics.length;
    const added = vscode.Uri.joinPath(valid.uri, 'node_modules/pkg/added.md');
    try {
      await writeText(added, 'Упоминание STEP-797 и STEP-701 внутри node_modules.\n');
      await sleep(1500);
      await refresh();
      const after = seams.getActiveArtifactSnapshot(valid);
      assert.equal(after?.diagnostics.length, diagnosticsBefore);
      assert.ok(
        after?.references.every((reference) => !reference.file.includes('node_modules')),
        'references from node_modules must not be indexed',
      );
      assert.deepEqual(artifactIds(after), artifactIds(snapshot));
    } finally {
      await removePath(added);
    }
  });
});
