import * as vscode from 'vscode';
import type { ArtifactIndex } from '../projectModel/artifactIndex';
import { idAtOffset } from '../navigation/idMatcher';
import type { NavigationContext } from '../navigation/harnessScope';

export interface NavigationTarget {
  readonly folder: vscode.WorkspaceFolder;
  readonly index: ArtifactIndex;
  readonly id: string;
  /** Якорь для peek: курсор редактора либо undefined для tree node. */
  readonly anchor?: { readonly uri: vscode.Uri; readonly position: vscode.Position };
}

interface TreeNodeLike {
  readonly artifact: { readonly id: string };
  readonly folder: vscode.WorkspaceFolder;
}

function isTreeNode(value: unknown): value is TreeNodeLike {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<TreeNodeLike>;
  return (
    typeof candidate.artifact === 'object' &&
    candidate.artifact !== null &&
    typeof candidate.artifact.id === 'string' &&
    typeof candidate.folder === 'object' &&
    candidate.folder !== null
  );
}

/**
 * Определяет ID для команды: узел tree view (STEP-004 leaf) либо курсор
 * активного Harness-aware Markdown; в canonical файле artifact вне ID
 * используется сам artifact.
 */
export function resolveNavigationTarget(
  context: NavigationContext,
  argument: unknown,
): NavigationTarget | undefined {
  if (isTreeNode(argument)) {
    const index = context.projectStates.getIndex(argument.folder);
    return index === undefined
      ? undefined
      : { folder: argument.folder, index, id: argument.artifact.id };
  }
  const editor = vscode.window.activeTextEditor;
  if (editor === undefined) return undefined;
  const scope = context.resolveScope(editor.document);
  if (scope === undefined) return undefined;
  const position = editor.selection.active;
  const hit = idAtOffset(editor.document.lineAt(position.line).text, position.character);
  const id = hit?.id ?? scope.index.getByFile(editor.document.uri.fsPath)?.id;
  if (id === undefined) return undefined;
  return {
    folder: scope.folder,
    index: scope.index,
    id,
    anchor: { uri: editor.document.uri, position },
  };
}
