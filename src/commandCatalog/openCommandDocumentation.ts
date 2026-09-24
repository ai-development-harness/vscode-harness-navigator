import { readFileSync } from 'node:fs';
import * as vscode from 'vscode';
import { COMMAND_CATALOG_MESSAGES as M } from './commandCatalogMessages';
import type { CatalogCommand } from './commandGraph';
import {
  findAnchorLine,
  parseDocumentationRef,
  resolveDocumentationPath,
} from './documentationTarget';

interface CommandNode {
  readonly type: 'command';
  readonly folder: vscode.WorkspaceFolder;
  readonly command: CatalogCommand;
}

function isCommandNode(value: unknown): value is CommandNode {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<CommandNode>;
  return (
    candidate.type === 'command' &&
    typeof candidate.folder === 'object' &&
    candidate.folder !== null &&
    typeof candidate.folder.uri?.fsPath === 'string' &&
    typeof candidate.command === 'object' &&
    candidate.command !== null &&
    typeof candidate.command.documentation === 'string'
  );
}

const info = (message: string, ...args: string[]): void => {
  void vscode.window.showInformationMessage(vscode.l10n.t(message, ...args));
};

async function openDocumentation(node: CommandNode): Promise<void> {
  const value = node.command.documentation;
  if (parseDocumentationRef(value).kind === 'empty') {
    info(M.docNone);
    return;
  }
  const resolved = resolveDocumentationPath(node.folder.uri.fsPath, value);
  switch (resolved.kind) {
    case 'empty':
      info(M.docNone);
      return;
    case 'unsafe':
      info(M.docBlocked);
      return;
    case 'missing':
      info(M.docNotFound, resolved.relativePath);
      return;
    case 'ok':
      break;
  }
  const line = ((): number | undefined => {
    try {
      return findAnchorLine(readFileSync(resolved.fsPath, 'utf8'), resolved.anchor);
    } catch {
      return undefined;
    }
  })();
  const document = await vscode.workspace.openTextDocument(vscode.Uri.file(resolved.fsPath));
  const editor = await vscode.window.showTextDocument(document);
  // Якорь не найден — явно «с начала»: VS Code иначе восстанавливает прежний курсор.
  const position = new vscode.Position(
    line === undefined ? 0 : Math.min(line, Math.max(document.lineCount - 1, 0)),
    0,
  );
  editor.selection = new vscode.Selection(position, position);
  editor.revealRange(
    new vscode.Range(position, position),
    vscode.TextEditorRevealType.InCenterIfOutsideViewport,
  );
}

/** `harnessNavigator.openCommandDocumentation`: только открытие документа, без записи и без исключений наружу. */
export function registerOpenCommandDocumentation(): vscode.Disposable {
  return vscode.commands.registerCommand(
    'harnessNavigator.openCommandDocumentation',
    async (node: unknown) => {
      if (!isCommandNode(node)) return;
      try {
        await openDocumentation(node);
      } catch {
        info(M.docNotFound, node.command.documentation);
      }
    },
  );
}
