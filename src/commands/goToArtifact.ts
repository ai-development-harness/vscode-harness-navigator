import * as vscode from 'vscode';
import {
  buildQuickPickCandidates,
  type QuickPickCandidate,
  type RootArtifacts,
} from '../views/artifactViewModel';
import { VIEW_MESSAGES } from '../views/viewMessages';
import type { ProjectStateService } from '../projectModel/projectStateService';

interface GoToArtifactQuickPickItem extends vscode.QuickPickItem {
  readonly candidate: QuickPickCandidate;
}

/**
 * Регистрирует `Harness: Go to Artifact`: собирает кандидатов по всем valid
 * roots через vscode-независимый `buildQuickPickCandidates`, показывает
 * штатный `showQuickPick` (`matchOnDescription`/`matchOnDetail` покрывают
 * fuzzy-поиск по title/kind без собственного алгоритма) и открывает
 * выбранный canonical Markdown через встроенную команду `vscode.open`.
 */
export function registerGoToArtifactCommand(projectStates: ProjectStateService): vscode.Disposable {
  return vscode.commands.registerCommand('harnessNavigator.goToArtifact', async () => {
    const folders = (vscode.workspace.workspaceFolders ?? []).filter(
      (folder) => projectStates.getIndex(folder) !== undefined,
    );
    const roots: RootArtifacts[] = folders.map((folder) => ({
      rootName: folder.name,
      artifacts: projectStates.getIndex(folder)?.snapshot().artifacts ?? [],
    }));
    const candidates = buildQuickPickCandidates(roots);
    if (candidates.length === 0) {
      void vscode.window.showInformationMessage(vscode.l10n.t(VIEW_MESSAGES.goToArtifactEmpty));
      return;
    }
    const items: GoToArtifactQuickPickItem[] = candidates.map((candidate) => ({
      label: candidate.artifact.id,
      description: candidate.artifact.title,
      detail:
        candidate.rootName === undefined
          ? candidate.artifact.kind
          : `${candidate.artifact.kind} · ${candidate.rootName}`,
      candidate,
    }));
    const picked = await vscode.window.showQuickPick(items, {
      placeHolder: vscode.l10n.t(VIEW_MESSAGES.goToArtifactPlaceholder),
      matchOnDescription: true,
      matchOnDetail: true,
    });
    if (picked === undefined) return;
    await vscode.commands.executeCommand(
      'vscode.open',
      vscode.Uri.file(picked.candidate.artifact.file),
    );
  });
}
