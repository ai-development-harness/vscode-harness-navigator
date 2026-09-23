import * as vscode from 'vscode';
import path from 'node:path';
import type { Artifact } from '../projectModel/artifactIndex';

interface CopyableArtifactNode {
  readonly artifact: Artifact;
  readonly folder: vscode.WorkspaceFolder;
}

function isCopyableArtifactNode(value: unknown): value is CopyableArtifactNode {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<CopyableArtifactNode>;
  return (
    typeof candidate.artifact === 'object' &&
    candidate.artifact !== null &&
    typeof candidate.folder === 'object' &&
    candidate.folder !== null
  );
}

/**
 * Регистрирует `harnessNavigator.copyArtifactId`/`copyArtifactPath` один раз
 * для обоих tree views (Artifacts View и Focus View используют одну и ту же
 * форму leaf-узла из `views/artifactTreeItem.ts`, см. `ArtifactLeafNode`).
 * Пишут только в `vscode.env.clipboard`; Harness artifacts не изменяются.
 */
export function registerCopyArtifactCommands(): vscode.Disposable[] {
  return [
    vscode.commands.registerCommand('harnessNavigator.copyArtifactId', async (node: unknown) => {
      if (!isCopyableArtifactNode(node)) return;
      await vscode.env.clipboard.writeText(node.artifact.id);
    }),
    vscode.commands.registerCommand('harnessNavigator.copyArtifactPath', async (node: unknown) => {
      if (!isCopyableArtifactNode(node)) return;
      const relative = path.relative(node.folder.uri.fsPath, node.artifact.file);
      await vscode.env.clipboard.writeText(relative);
    }),
  ];
}
