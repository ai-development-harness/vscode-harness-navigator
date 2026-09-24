import * as assert from 'node:assert/strict';
import * as vscode from 'vscode';
import { assertIsolatedWorkspace } from './support/workspaceGuard';

const encoder = new TextEncoder();
const EXTENSION_ID = 'ai-development-harness.vscode-harness-navigator';
const russian = () => vscode.env.language.toLowerCase().startsWith('ru');

interface ExtensionModule {
  getActiveArtifactSnapshot: (
    folder: vscode.WorkspaceFolder,
  ) => { artifacts: { id: string; file: string; title: string }[] } | undefined;
}

const doc = (id: string, fields: string, title: string) =>
  `---\nschema: 1\nid: ${id}\n${fields}---\n\n# ${id} — ${title}\n`;

async function pollFor(predicate: () => boolean | Promise<boolean>): Promise<boolean> {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (await predicate()) return true;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return false;
}

function locationKey(location: { uri: vscode.Uri; range: vscode.Range }): string {
  const { start, end } = location.range;
  return `${location.uri.fsPath}:${start.line}:${start.character}-${end.line}:${end.character}`;
}

suite('navigation, references и relations (Extension Host)', () => {
  suiteSetup(() => assertIsolatedWorkspace());

  test('providers, references, relations, diagnostics и semantic tokens в Harness-aware области', async () => {
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension);
    await extension.activate();
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const extensionModule = require(
      extension.extensionPath + '/dist/extension.js',
    ) as ExtensionModule;
    const valid = vscode.workspace.workspaceFolders?.find((f) => f.name === 'valid-project');
    const ordinary = vscode.workspace.workspaceFolders?.find((f) => f.name === 'ordinary-folder');
    assert.ok(valid);
    assert.ok(ordinary);
    // Fixtures создаются во время выполнения и полностью удаляются в finally;
    // статических docs/planning в valid-project нет.
    for (const directory of ['planning', 'docs'])
      await assert.rejects(
        Promise.resolve(vscode.workspace.fs.stat(vscode.Uri.joinPath(valid.uri, directory))),
      );
    const step = vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-950.md');
    const req = vscode.Uri.joinPath(valid.uri, 'docs/requirements/REQ-950.md');
    const guide = vscode.Uri.joinPath(valid.uri, 'docs/guides/nav.md');
    const outside = vscode.Uri.joinPath(ordinary.uri, 'outside-nav.md');
    const text = 'See REQ-950 and STEP-950 and REQ-999.\nType: STEP-\n';
    const originalFetch = vscode.commands.executeCommand;
    const originalQuickPick = vscode.window.showQuickPick;
    try {
      await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(valid.uri, 'planning/tasks'));
      await vscode.workspace.fs.createDirectory(
        vscode.Uri.joinPath(valid.uri, 'docs/requirements'),
      );
      await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(valid.uri, 'docs/guides'));
      await vscode.workspace.fs.writeFile(
        step,
        encoder.encode(
          doc(
            'STEP-950',
            'status: planned\nrequirements:\n  - REQ-950\n  - REQ-998\n',
            'Навигация',
          ),
        ),
      );
      await vscode.workspace.fs.writeFile(
        req,
        encoder.encode(doc('REQ-950', 'status: draft\n', 'Требование')),
      );
      await vscode.workspace.fs.writeFile(guide, encoder.encode(text));
      await vscode.workspace.fs.writeFile(outside, encoder.encode(text));
      await vscode.commands.executeCommand('harnessNavigator.refresh');
      assert.ok(
        await pollFor(
          () =>
            extensionModule
              .getActiveArtifactSnapshot(valid)
              ?.artifacts.some((item) => item.id === 'REQ-950') === true,
        ),
      );

      const guideDocument = await vscode.workspace.openTextDocument(guide);
      await vscode.window.showTextDocument(guideDocument);
      const onReq = new vscode.Position(0, 6);
      const onUnknown = new vscode.Position(0, 35);
      const typing = new vscode.Position(1, 11);

      // Definition
      const definitions = await vscode.commands.executeCommand<
        (vscode.Location | vscode.LocationLink)[]
      >('vscode.executeDefinitionProvider', guide, onReq);
      const first = definitions[0];
      assert.ok(first);
      const definitionUri = 'targetUri' in first ? first.targetUri : first.uri;
      assert.equal(definitionUri.fsPath, req.fsPath);
      assert.deepEqual(
        await vscode.commands.executeCommand('vscode.executeDefinitionProvider', guide, onUnknown),
        [],
      );

      // Document links: только известные ID
      const links = await vscode.commands.executeCommand<vscode.DocumentLink[]>(
        'vscode.executeLinkProvider',
        guide,
      );
      const harnessLinks = links.filter((link) => link.target?.fsPath.endsWith('.md') === true);
      assert.deepEqual(
        harnessLinks.map((link) => link.target?.fsPath).sort(),
        [req.fsPath, step.fsPath].sort(),
      );

      // Hover (локализованный) и unknown → пусто
      const hovers = await vscode.commands.executeCommand<vscode.Hover[]>(
        'vscode.executeHoverProvider',
        guide,
        onReq,
      );
      const hoverText = hovers
        .flatMap((hover) => hover.contents)
        .map((content) => (typeof content === 'string' ? content : content.value))
        .join('\n')
        // appendText кодирует пробелы как &nbsp; (защита недоверенного текста).
        .replace(/&nbsp;/gu, ' ');
      assert.ok(hoverText.includes('REQ-950'));
      assert.ok(hoverText.includes(russian() ? 'Тип: REQ' : 'Kind: REQ'));
      assert.ok(hoverText.includes(russian() ? 'Статус: ' : 'Status: '));
      assert.equal(
        (
          await vscode.commands.executeCommand<vscode.Hover[]>(
            'vscode.executeHoverProvider',
            guide,
            onUnknown,
          )
        ).length,
        0,
      );

      // Completion вставляет только canonical ID
      const completions = await vscode.commands.executeCommand<vscode.CompletionList>(
        'vscode.executeCompletionItemProvider',
        guide,
        typing,
      );
      const stepItem = completions.items.find((item) => item.label === 'STEP-950');
      assert.ok(stepItem);
      assert.equal(stepItem.insertText, 'STEP-950');
      assert.ok(
        completions.items
          .filter((item) => typeof item.label === 'string' && item.label.startsWith('STEP-'))
          .every((item) => item.insertText === item.label),
      );

      // References: definition не включён, editor == tree node == relations
      const provided = await vscode.commands.executeCommand<vscode.Location[]>(
        'vscode.executeReferenceProvider',
        guide,
        onReq,
      );
      const mentions = provided.filter((location) => location.uri.fsPath !== req.fsPath);
      assert.equal(mentions.length, 2, 'STEP-950 relation и упоминание в guide');
      assert.ok(mentions.some((location) => location.uri.fsPath === guide.fsPath));
      const snapshot = extensionModule.getActiveArtifactSnapshot(valid);
      const reqArtifact = snapshot?.artifacts.find((item) => item.id === 'REQ-950');
      assert.ok(reqArtifact);
      const editor = vscode.window.activeTextEditor;
      assert.ok(editor);
      editor.selection = new vscode.Selection(onReq, onReq);
      const fromEditor = await vscode.commands.executeCommand<vscode.Location[]>(
        'harnessNavigator.findAllReferences',
      );
      const fromNode = await vscode.commands.executeCommand<vscode.Location[]>(
        'harnessNavigator.findAllReferences',
        { artifact: reqArtifact, folder: valid },
      );
      const keys = (locations: vscode.Location[]) => locations.map(locationKey).sort();
      assert.deepEqual(keys(fromEditor), keys(mentions));
      assert.deepEqual(keys(fromNode), keys(mentions));
      assert.ok(fromNode.every((location) => location.uri.fsPath !== req.fsPath));

      // STEP-014: menu-only алиас editor/context делегирует оригиналу с пробросом аргумента
      const aliasFromEditor = await vscode.commands.executeCommand<vscode.Location[]>(
        'harnessNavigator.editor.findAllReferences',
      );
      // активный редактор — step без ID под курсором: без проброса аргумента цели не будет
      await vscode.window.showTextDocument(step, { selection: new vscode.Range(0, 0, 0, 0) });
      const aliasFromNode = await vscode.commands.executeCommand<vscode.Location[]>(
        'harnessNavigator.editor.findAllReferences',
        { artifact: reqArtifact, folder: valid },
      );
      assert.deepEqual(keys(aliasFromEditor), keys(fromEditor));
      assert.ok(aliasFromNode.length > 0);
      assert.deepEqual(keys(aliasFromNode), keys(fromNode));

      // Show Relations: клик открывает файл, Find All References даёт те же Location
      let offered: vscode.QuickPickItem[] = [];
      const pick = (label: string) => {
        (vscode.window as { showQuickPick: unknown }).showQuickPick = async (items: unknown) => {
          offered = (await Promise.resolve(items)) as vscode.QuickPickItem[];
          return offered.find((item) => item.label.includes(label));
        };
      };
      pick('STEP-950');
      await vscode.commands.executeCommand('harnessNavigator.showRelations', {
        artifact: reqArtifact,
        folder: valid,
      });
      assert.ok(offered.some((item) => item.kind === vscode.QuickPickItemKind.Separator));
      assert.ok(offered.some((item) => item.label === 'STEP-950'));
      assert.equal(vscode.window.activeTextEditor?.document.uri.fsPath, step.fsPath);

      const originalOffered = offered.map((item) => item.label);
      // активен step: без проброса аргумента цель была бы STEP-950, а не REQ-950
      offered = [];
      await vscode.commands.executeCommand('harnessNavigator.editor.showRelations', {
        artifact: reqArtifact,
        folder: valid,
      });
      assert.ok(originalOffered.length > 0);
      assert.deepEqual(
        offered.map((item) => item.label),
        originalOffered,
        'алиас showRelations предлагает те же пункты и пробрасывает аргумент',
      );
      assert.equal(vscode.window.activeTextEditor?.document.uri.fsPath, step.fsPath);

      const forwarded: Thenable<unknown>[] = [];
      (vscode.commands as { executeCommand: unknown }).executeCommand = (
        command: string,
        ...args: unknown[]
      ) => {
        const result = originalFetch.call(vscode.commands, command, ...args);
        if (command === 'harnessNavigator.findAllReferences') forwarded.push(result);
        return result;
      };
      pick('$(references)');
      await vscode.commands.executeCommand('harnessNavigator.showRelations', {
        artifact: reqArtifact,
        folder: valid,
      });
      (vscode.commands as { executeCommand: unknown }).executeCommand = originalFetch;
      assert.equal(forwarded.length, 1);
      assert.deepEqual(keys((await forwarded[0]) as vscode.Location[]), keys(mentions));

      // Dangling relation не бросает
      pick('REQ-998');
      await vscode.commands.executeCommand('harnessNavigator.showRelations', {
        artifact: snapshot?.artifacts.find((item) => item.id === 'STEP-950'),
        folder: valid,
      });
      assert.ok(offered.some((item) => item.label === 'REQ-998'));

      // Diagnostics: только неизвестный ID, локализованно
      assert.ok(
        await pollFor(() => vscode.languages.getDiagnostics(guide).length > 0),
        'diagnostics for unknown id',
      );
      const diagnostics = vscode.languages.getDiagnostics(guide);
      assert.equal(diagnostics.length, 1);
      assert.equal(
        diagnostics[0]?.message,
        russian()
          ? 'Идентификатор Harness REQ-999 не найден в этом проекте.'
          : 'The Harness identifier REQ-999 was not found in this project.',
      );

      // Semantic tokens: по токену на известный ID
      const tokens = await vscode.commands.executeCommand<vscode.SemanticTokens | undefined>(
        'vscode.provideDocumentSemanticTokens',
        guide,
      );
      assert.equal(tokens?.data.length, 10);

      // Вне Harness-aware области — никакой semantic функциональности
      const outsideDocument = await vscode.workspace.openTextDocument(outside);
      await vscode.window.showTextDocument(outsideDocument);
      assert.deepEqual(
        await vscode.commands.executeCommand('vscode.executeDefinitionProvider', outside, onReq),
        [],
      );
      assert.equal(
        (
          await vscode.commands.executeCommand<vscode.Hover[]>(
            'vscode.executeHoverProvider',
            outside,
            onReq,
          )
        ).length,
        0,
      );
      assert.equal(
        (
          await vscode.commands.executeCommand<vscode.CompletionList>(
            'vscode.executeCompletionItemProvider',
            outside,
            typing,
          )
        ).items.filter((item) => item.label === 'STEP-950').length,
        0,
      );
      assert.deepEqual(vscode.languages.getDiagnostics(outside), []);
      const outsideTokens = await vscode.commands.executeCommand<vscode.SemanticTokens | undefined>(
        'vscode.provideDocumentSemanticTokens',
        outside,
      );
      assert.equal(outsideTokens?.data.length ?? 0, 0);
    } finally {
      (vscode.commands as { executeCommand: unknown }).executeCommand = originalFetch;
      (vscode.window as { showQuickPick: unknown }).showQuickPick = originalQuickPick;
      await vscode.commands.executeCommand('workbench.action.closeAllEditors');
      for (const target of ['planning', 'docs']) {
        await vscode.workspace.fs.delete(vscode.Uri.joinPath(valid.uri, target), {
          recursive: true,
          useTrash: false,
        });
      }
      await vscode.workspace.fs.delete(outside, { useTrash: false });
      await vscode.commands.executeCommand('harnessNavigator.refresh');
    }
  });
});
