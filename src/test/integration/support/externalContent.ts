import * as assert from 'node:assert/strict';
import * as vscode from 'vscode';
import {
  flatten,
  positionOf,
  showDiagnostics,
  stubQuickPick,
  type ExtensionSeams,
} from './helpers';

const EXTERNAL_TOKENS = ['STEP-990', 'STEP-991', 'Внешний шаг'];

/** Ни один ID/текст из mvp-external не должен проявиться ни в одном derived представлении. */
export async function assertNoExternalContent(
  seams: ExtensionSeams,
  valid: vscode.WorkspaceFolder,
): Promise<void> {
  const texts: string[] = [];
  const addNodes = (
    nodes: readonly {
      label: string;
      description: string | undefined;
      tooltip?: string | undefined;
      children: readonly unknown[];
    }[],
  ) => {
    for (const node of flatten(nodes as never)) {
      texts.push(node.label, node.description ?? '');
      const tooltip = (node as { tooltip?: string }).tooltip;
      if (tooltip !== undefined) texts.push(tooltip);
    }
  };
  addNodes(seams.getArtifactsViewSnapshot());
  addNodes(seams.getFocusViewSnapshot());
  addNodes(seams.getSummaryViewSnapshot());
  addNodes(seams.getCommandsViewSnapshot());
  const status = seams.getStatusBarSnapshot();
  texts.push(status?.text ?? '', status?.tooltip ?? '');
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const snapshot = seams.getActiveArtifactSnapshot(folder);
    for (const artifact of snapshot?.artifacts ?? [])
      texts.push(artifact.id, artifact.title, artifact.file);
    for (const reference of (
      snapshot as { references?: { targetId: string; file: string }[] } | undefined
    )?.references ?? [])
      texts.push(reference.targetId, reference.file);
  }
  const report = await showDiagnostics();
  texts.push(...report.lines);
  // Go to Artifact candidates.
  const picker = stubQuickPick(() => undefined);
  try {
    await vscode.commands.executeCommand('harnessNavigator.goToArtifact');
    for (const item of picker.offered())
      texts.push(item.label, item.description ?? '', item.detail ?? '');
  } finally {
    picker.restore();
  }
  // definition/references для внешних ID.
  const document = await vscode.workspace.openTextDocument(
    vscode.Uri.joinPath(valid.uri, 'docs/guides/guide.md'),
  );
  const references = await vscode.commands.executeCommand<vscode.Location[]>(
    'vscode.executeReferenceProvider',
    document.uri,
    positionOf(document, 'STEP-701'),
  );
  for (const location of references) texts.push(location.uri.fsPath);
  const joined = texts.join('\n');
  for (const token of EXTERNAL_TOKENS)
    assert.ok(!joined.includes(token), `external content "${token}" leaked into derived state`);
  assert.ok(!joined.includes('mvp-external'), 'mvp-external path leaked into derived state');
}
