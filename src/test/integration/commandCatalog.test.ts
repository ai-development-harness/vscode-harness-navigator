import * as assert from 'node:assert/strict';
import * as vscode from 'vscode';
import { assertIsolatedWorkspace } from './support/workspaceGuard';

const encoder = new TextEncoder();
const EXTENSION_ID = 'ai-development-harness.vscode-harness-navigator';
const russian = () => vscode.env.language.toLowerCase().startsWith('ru');

interface CommandNodeSnapshot {
  readonly label: string;
  readonly description: string | undefined;
  readonly tooltip: string | undefined;
  readonly contextValue: string | undefined;
  readonly hasCommand: boolean;
  readonly children: readonly CommandNodeSnapshot[];
}

interface ExtensionModule {
  getActiveArtifactSnapshot: (
    folder: vscode.WorkspaceFolder,
  ) => { artifacts: { id: string }[] } | undefined;
  getCommandCatalogState: (folder: vscode.WorkspaceFolder) => { kind: string } | undefined;
  getCommandsViewSnapshot: () => readonly CommandNodeSnapshot[];
  getCommandsViewMessage: () => string | undefined;
  getCommandsViewCommandNodes: () => readonly { command: { canonical: string } }[];
  getArtifactsViewArtifactNodes: () => readonly {
    folder: vscode.WorkspaceFolder;
    artifact: { id: string; kind: string };
  }[];
}

interface Graph {
  schemaVersion: number;
  domains: Record<string, { commands: Record<string, unknown> }>;
}

const GRAPH_PATH = '.harness/command-transitions.json';

const graphText = (mutate: (graph: Graph) => void = () => undefined): string => {
  const graph: Graph = {
    schemaVersion: 1,
    domains: {
      STEP: {
        commands: {
          LIST: {
            canonical: 'STEP LIST',
            chainAllowed: false,
            target: 'none',
            input: 'none',
            summary: 'Graph summary of list.',
            documentation: '.harness/docs/COMMANDS.md#command-step-list',
            dispatch: { kind: 'deterministic' },
          },
          PLAN: {
            canonical: 'STEP PLAN STEP-NNN',
            chainAllowed: true,
            target: 'step',
            input: 'none',
            summary: 'Graph summary of plan.',
            dispatch: { kind: 'semantic' },
          },
          REVIEW: {
            canonical: 'STEP REVIEW STEP-NNN',
            chainAllowed: true,
            target: 'step',
            input: 'none',
            summary: 'Graph summary of review.',
            dispatch: { kind: 'semantic' },
          },
        },
      },
      PROJECT: {
        commands: {
          'QUICK FIX': {
            canonical: 'PROJECT QUICK FIX:',
            chainAllowed: false,
            target: 'none',
            input: 'required',
            summary: 'Graph summary of quick fix.',
            dispatch: { kind: 'semantic' },
          },
        },
      },
      FUTURE: {
        commands: {
          ZAP: {
            canonical: 'FUTURE ZAP',
            chainAllowed: false,
            target: 'quantum',
            input: 'maybe',
            summary: 'Future command summary.',
            dispatch: { kind: 'telepathy' },
          },
        },
      },
    },
  };
  mutate(graph);
  return JSON.stringify(graph);
};

async function pollFor(
  predicate: () => boolean | Promise<boolean>,
  attempts = 30,
  intervalMs = 100,
): Promise<boolean> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (await predicate()) return true;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return false;
}

/**
 * Watcher-only окно, затем документированный REQ-009 recovery через
 * `harnessNavigator.refresh` (F-018). Возвращает сработавший путь и логирует его
 * для Evidence.
 */
async function converge(
  predicate: () => boolean | Promise<boolean>,
): Promise<'watcher' | 'refresh fallback' | undefined> {
  if (await pollFor(predicate)) {
    console.log('[commandCatalog] graph change observed via watcher');
    return 'watcher';
  }
  await vscode.commands.executeCommand('harnessNavigator.refresh');
  if (await pollFor(predicate)) {
    console.log('[commandCatalog] graph change observed via refresh fallback');
    return 'refresh fallback';
  }
  return undefined;
}

const flatten = (nodes: readonly CommandNodeSnapshot[]): CommandNodeSnapshot[] =>
  nodes.flatMap((node) => [node, ...flatten(node.children)]);

const stepDoc = (id: string) =>
  `---\nschema: 1\nid: ${id}\nstatus: planned\n---\n\n# ${id} — Каталог\n`;
const reqDoc = (id: string) =>
  `---\nschema: 1\nid: ${id}\nstatus: draft\n---\n\n# ${id} — Требование\n`;

suite('Command Catalog (Extension Host)', () => {
  suiteSetup(() => assertIsolatedWorkspace());

  let extensionModule: ExtensionModule;
  let valid: vscode.WorkspaceFolder;
  let graphUri: vscode.Uri;
  let originalClipboard = '';
  const original = {
    quickPick: vscode.window.showQuickPick,
    info: vscode.window.showInformationMessage,
  };

  suiteSetup(async () => {
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension);
    await extension.activate();
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    extensionModule = require(extension.extensionPath + '/dist/extension.js') as ExtensionModule;
    const folder = vscode.workspace.workspaceFolders?.find((f) => f.name === 'valid-project');
    assert.ok(folder);
    valid = folder;
    graphUri = vscode.Uri.joinPath(valid.uri, GRAPH_PATH);
    // Clipboard недоступен в окружении → ошибка чтения проваливает тест, а не даёт ложный PASS
    // (в Evidence это BLOCKED).
    originalClipboard = await vscode.env.clipboard.readText();
  });

  teardown(async () => {
    (vscode.window as { showQuickPick: unknown }).showQuickPick = original.quickPick;
    (vscode.window as { showInformationMessage: unknown }).showInformationMessage = original.info;
    await vscode.workspace.fs.delete(graphUri, { useTrash: false }).then(
      () => undefined,
      () => undefined,
    );
    for (const target of ['planning', 'docs', '.harness/docs']) {
      await vscode.workspace.fs
        .delete(vscode.Uri.joinPath(valid.uri, target), { recursive: true, useTrash: false })
        .then(
          () => undefined,
          () => undefined,
        );
    }
    await vscode.commands.executeCommand('harnessNavigator.refresh');
  });

  suiteTeardown(async () => {
    await vscode.env.clipboard.writeText(originalClipboard);
  });

  const writeGraph = (text: string) =>
    vscode.workspace.fs.writeFile(graphUri, encoder.encode(text));

  const loadGraph = async (text: string, kind: string) => {
    await writeGraph(text);
    const path = await converge(() => extensionModule.getCommandCatalogState(valid)?.kind === kind);
    assert.ok(path, `catalog did not reach "${kind}" through watcher or refresh`);
  };

  const diagnosticLines = async (): Promise<string[]> =>
    (await vscode.commands.executeCommand<{ lines: string[] }>('harnessNavigator.showDiagnostics'))
      .lines;

  test('отсутствующий граф: изолированная ошибка и CommandGraphReadError, Artifacts View не затронут', async () => {
    await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(valid.uri, 'planning/tasks'));
    await vscode.workspace.fs.writeFile(
      vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-960.md'),
      encoder.encode(stepDoc('STEP-960')),
    );
    await vscode.commands.executeCommand('harnessNavigator.refresh');
    assert.equal(extensionModule.getCommandCatalogState(valid)?.kind, 'readError');
    assert.equal(
      extensionModule.getCommandsViewMessage(),
      russian()
        ? 'Граф команд Harness недоступен. Подробности смотрите в диагностике Harness.'
        : 'The Harness command graph is unavailable. Open the Harness diagnostics for details.',
    );
    assert.deepEqual(extensionModule.getCommandsViewSnapshot(), []);
    assert.ok(
      extensionModule.getActiveArtifactSnapshot(valid)?.artifacts.some((a) => a.id === 'STEP-960'),
    );
    const lines = await diagnosticLines();
    assert.ok(
      lines.some(
        (line) =>
          line.includes('CommandGraphReadError') &&
          line.includes(
            russian()
              ? 'Не удалось прочитать граф команд Harness.'
              : 'The Harness command graph cannot be read.',
          ),
      ),
    );
  });

  test('Commands View показывает домены и команды графа, будущую команду и fallback description', async () => {
    await loadGraph(graphText(), 'ready');
    const snapshot = extensionModule.getCommandsViewSnapshot();
    // Multi-root workspace: root -> domain -> command; один valid root => domains сразу.
    assert.deepEqual(
      snapshot.map((node) => node.label),
      ['STEP', 'PROJECT', 'FUTURE'],
    );
    assert.equal(extensionModule.getCommandsViewMessage(), '');
    const nodes = flatten(snapshot).filter((node) => node.contextValue === 'harnessCommandItem');
    assert.equal(nodes.length, 5);
    assert.ok(
      nodes.every((node) => !node.hasCommand),
      'узлы не должны выполнять команды',
    );
    const list = nodes.find((node) => node.label === 'STEP LIST');
    assert.equal(
      list?.description,
      russian() ? 'Показать список задач и их состояний' : 'List tasks and their states',
    );
    assert.ok(list?.tooltip?.includes(russian() ? 'Домен: STEP' : 'Domain: STEP'));
    assert.ok(list?.tooltip?.includes('command-step-list'));
    const future = nodes.find((node) => node.label === 'FUTURE ZAP');
    assert.equal(future?.description, 'Future command summary.');
    assert.ok(future?.tooltip?.includes('quantum'));
    const plan = nodes.find((node) => node.label === 'STEP PLAN STEP-NNN');
    assert.ok(plan?.tooltip?.includes(russian() ? 'Цепочка:' : 'Chain:'));
  });

  test('Find Command копирует шаблон в clipboard и не создаёт terminals', async () => {
    await loadGraph(graphText(), 'ready');
    const terminalsBefore = vscode.window.terminals.length;
    let offered: (vscode.QuickPickItem & { template?: string })[] = [];
    (vscode.window as { showQuickPick: unknown }).showQuickPick = async (items: unknown) => {
      offered = (await Promise.resolve(items)) as typeof offered;
      return offered.find((item) => item.label === 'PROJECT QUICK FIX:');
    };
    await vscode.env.clipboard.writeText('sentinel');
    await vscode.commands.executeCommand('harnessNavigator.findCommand');
    assert.deepEqual(
      offered.map((item) => item.label).sort(),
      [
        'FUTURE ZAP',
        'PROJECT QUICK FIX:',
        'STEP LIST',
        'STEP PLAN STEP-NNN',
        'STEP REVIEW STEP-NNN',
      ].sort(),
    );
    assert.equal(await vscode.env.clipboard.readText(), 'PROJECT QUICK FIX: <…>');
    assert.equal(vscode.window.terminals.length, terminalsBefore);
  });

  test('Copy Command из узла Commands View копирует шаблон', async () => {
    await loadGraph(graphText(), 'ready');
    const terminalsBefore = vscode.window.terminals.length;
    const node = extensionModule
      .getCommandsViewCommandNodes()
      .find((candidate) => candidate.command.canonical === 'STEP PLAN STEP-NNN');
    assert.ok(node);
    await vscode.commands.executeCommand('harnessNavigator.copyCommand', node);
    assert.equal(await vscode.env.clipboard.readText(), 'STEP PLAN STEP-NNN');
    assert.equal(vscode.window.terminals.length, terminalsBefore);
  });

  test('Copy Command из STEP-узла Artifacts View подставляет STEP ID; для REQ отказывает', async () => {
    await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(valid.uri, 'planning/tasks'));
    await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(valid.uri, 'docs/requirements'));
    await vscode.workspace.fs.writeFile(
      vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-960.md'),
      encoder.encode(stepDoc('STEP-960')),
    );
    await vscode.workspace.fs.writeFile(
      vscode.Uri.joinPath(valid.uri, 'docs/requirements/REQ-960.md'),
      encoder.encode(reqDoc('REQ-960')),
    );
    await loadGraph(graphText(), 'ready');
    await vscode.commands.executeCommand('harnessNavigator.refresh');
    assert.ok(
      await pollFor(() => extensionModule.getArtifactsViewArtifactNodes().length >= 2),
      'artifacts did not appear',
    );
    const terminalsBefore = vscode.window.terminals.length;
    const stepNode = extensionModule
      .getArtifactsViewArtifactNodes()
      .find((node) => node.artifact.id === 'STEP-960');
    const reqNode = extensionModule
      .getArtifactsViewArtifactNodes()
      .find((node) => node.artifact.id === 'REQ-960');
    assert.ok(stepNode);
    assert.ok(reqNode);

    let offered: string[] = [];
    (vscode.window as { showQuickPick: unknown }).showQuickPick = async (items: unknown) => {
      const list = (await Promise.resolve(items)) as vscode.QuickPickItem[];
      offered = list.map((item) => item.label);
      return list.find((item) => item.label === 'STEP REVIEW STEP-960');
    };
    await vscode.env.clipboard.writeText('sentinel');
    await vscode.commands.executeCommand('harnessNavigator.copyCommand', stepNode);
    assert.deepEqual(offered, ['STEP PLAN STEP-960', 'STEP REVIEW STEP-960']);
    assert.equal(await vscode.env.clipboard.readText(), 'STEP REVIEW STEP-960');

    let message = '';
    (vscode.window as { showInformationMessage: unknown }).showInformationMessage = (
      text: string,
    ) => {
      message = text;
      return Promise.resolve(undefined);
    };
    await vscode.env.clipboard.writeText('sentinel');
    await vscode.commands.executeCommand('harnessNavigator.copyCommand', reqNode);
    assert.equal(await vscode.env.clipboard.readText(), 'sentinel');
    assert.equal(
      message,
      russian()
        ? 'Выберите артефакт STEP, чтобы скопировать команду STEP.'
        : 'Select a STEP artifact to copy a STEP command.',
    );
    assert.equal(vscode.window.terminals.length, terminalsBefore);
  });

  test('изменение графа обновляет каталог без перезапуска Extension Host', async () => {
    await loadGraph(graphText(), 'ready');
    const changed = graphText((graph) => {
      const future = graph.domains.FUTURE;
      assert.ok(future);
      future.commands.ZAP2 = {
        canonical: 'FUTURE ZAP2',
        chainAllowed: false,
        target: 'none',
        input: 'none',
        summary: 'Second future command.',
        dispatch: { kind: 'deterministic' },
      };
    });
    await writeGraph(changed);
    const path = await converge(() =>
      flatten(extensionModule.getCommandsViewSnapshot()).some(
        (node) => node.label === 'FUTURE ZAP2',
      ),
    );
    assert.ok(path, 'ни watcher, ни "Harness: Refresh" не обновили Commands View');
  });

  test('неподдерживаемая schema изолирована: Commands View — ошибка, Artifacts View работает', async () => {
    await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(valid.uri, 'planning/tasks'));
    await vscode.workspace.fs.writeFile(
      vscode.Uri.joinPath(valid.uri, 'planning/tasks/STEP-960.md'),
      encoder.encode(stepDoc('STEP-960')),
    );
    await loadGraph(
      graphText((graph) => {
        graph.schemaVersion = 2;
      }),
      'unsupportedSchema',
    );
    assert.equal(
      extensionModule.getCommandsViewMessage(),
      russian()
        ? 'Schema графа команд Harness не поддерживается. Подробности смотрите в диагностике Harness.'
        : 'The Harness command graph schema is not supported. Open the Harness diagnostics for details.',
    );
    assert.deepEqual(extensionModule.getCommandsViewSnapshot(), []);
    assert.ok(
      await pollFor(
        () =>
          extensionModule
            .getActiveArtifactSnapshot(valid)
            ?.artifacts.some((a) => a.id === 'STEP-960') === true,
      ),
    );
    assert.ok(
      (await diagnosticLines()).some((line) => line.includes('CommandGraphUnsupportedSchema')),
    );

    await loadGraph('{ malformed', 'readError');
    assert.ok((await diagnosticLines()).some((line) => line.includes('CommandGraphReadError')));
  });

  const DOCS_PATH = '.harness/docs/COMMANDS.md';
  const writeDocs = async () => {
    await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(valid.uri, '.harness/docs'));
    await vscode.workspace.fs.writeFile(
      vscode.Uri.joinPath(valid.uri, DOCS_PATH),
      encoder.encode(
        '# Commands\n\nintro\n\n<a id="command-step-list"></a>\n## STEP LIST\n\ntext\n',
      ),
    );
  };
  const commandNode = (canonical: string) => {
    const node = extensionModule
      .getCommandsViewCommandNodes()
      .find((candidate) => candidate.command.canonical === canonical);
    assert.ok(node, canonical);
    return node;
  };
  const openedEditorPath = () => vscode.window.activeTextEditor?.document.uri.fsPath;

  test('openCommandDocumentation: manifest, палитра и меню', () => {
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension);
    const contributes = (extension.packageJSON as { contributes: unknown }).contributes as {
      commands: { command: string; category?: string; title: string }[];
      menus: Record<string, { command: string; when?: string; group?: string }[]>;
    };
    const declared = contributes.commands.find(
      (entry) => entry.command === 'harnessNavigator.openCommandDocumentation',
    );
    assert.ok(declared);
    assert.ok(declared.category);
    assert.ok(!declared.title.startsWith('Harness'));
    const expected = russian() ? 'Открыть документацию' : 'Open Documentation';
    assert.ok(
      declared.title === expected || declared.title === '%command.openCommandDocumentation.title%',
      declared.title,
    );
    assert.equal(
      contributes.menus.commandPalette?.find(
        (entry) => entry.command === 'harnessNavigator.openCommandDocumentation',
      )?.when,
      'false',
    );
    const items = contributes.menus['view/item/context'] ?? [];
    const groupOf = (command: string) =>
      items.find(
        (entry) =>
          entry.command === command && entry.when?.includes('viewItem == harnessCommandItem'),
      )?.group;
    assert.equal(groupOf('harnessNavigator.copyCommand'), 'navigation@1');
    assert.equal(groupOf('harnessNavigator.openCommandDocumentation'), 'navigation@2');
  });

  test('openCommandDocumentation: открывает файл на секции якоря', async () => {
    await writeDocs();
    await loadGraph(graphText(), 'ready');
    await vscode.commands.executeCommand('workbench.action.closeAllEditors');
    await vscode.commands.executeCommand(
      'harnessNavigator.openCommandDocumentation',
      commandNode('STEP LIST'),
    );
    const editor = vscode.window.activeTextEditor;
    assert.ok(editor);
    assert.equal(editor.document.uri.fsPath.endsWith('COMMANDS.md'), true);
    assert.equal(editor.selection.active.line, 5);
  });

  test('openCommandDocumentation: отсутствующий якорь — курсор в начале', async () => {
    await writeDocs();
    await loadGraph(
      graphText((graph) => {
        (graph.domains.STEP?.commands.LIST as { documentation: string }).documentation =
          '.harness/docs/COMMANDS.md#no-such-anchor';
      }),
      'ready',
    );
    await vscode.commands.executeCommand('workbench.action.closeAllEditors');
    await vscode.commands.executeCommand(
      'harnessNavigator.openCommandDocumentation',
      commandNode('STEP LIST'),
    );
    assert.equal(vscode.window.activeTextEditor?.selection.active.line, 0);
  });

  const rejected: [string, string][] = [
    ['пустое documentation', ''],
    ['отсутствующий файл', '.harness/docs/MISSING.md#x'],
    ['traversal', '../outside.md#x'],
    ['абсолютный путь', '/etc/hostname'],
  ];
  for (const [name, documentation] of rejected) {
    test(`openCommandDocumentation: ${name} — редактор не открывается, без исключений`, async () => {
      await writeDocs();
      await loadGraph(
        graphText((graph) => {
          (graph.domains.STEP?.commands.LIST as { documentation: string }).documentation =
            documentation;
        }),
        'ready',
      );
      const messages: string[] = [];
      (vscode.window as { showInformationMessage: unknown }).showInformationMessage = (
        message: string,
      ) => {
        messages.push(message);
        return Promise.resolve(undefined);
      };
      await vscode.commands.executeCommand('workbench.action.closeAllEditors');
      await vscode.commands.executeCommand(
        'harnessNavigator.openCommandDocumentation',
        commandNode('STEP LIST'),
      );
      assert.equal(openedEditorPath(), undefined);
      assert.equal(messages.length, 1);
    });
  }
});
