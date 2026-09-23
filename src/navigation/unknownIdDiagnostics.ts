import * as vscode from 'vscode';
import { MAXIMUM_MARKDOWN_SIZE_BYTES } from '../projectModel/artifactIndex';
import { scanIds } from './idMatcher';
import type { NavigationContext } from './harnessScope';
import { NAVIGATION_MESSAGES } from './navigationMessages';

/**
 * Warning на неизвестный ID только в открытых Harness-aware документах.
 * Документ вне области, закрытый или потерявший область очищается.
 */
export class UnknownIdDiagnostics implements vscode.Disposable {
  private readonly collection = vscode.languages.createDiagnosticCollection('Harness Navigator');
  private readonly subscriptions: vscode.Disposable[] = [];

  constructor(private readonly context: NavigationContext) {
    this.subscriptions.push(
      vscode.workspace.onDidOpenTextDocument((document) => this.refresh(document)),
      vscode.workspace.onDidChangeTextDocument((event) => this.refresh(event.document)),
      vscode.workspace.onDidCloseTextDocument((document) => this.collection.delete(document.uri)),
    );
    this.refreshAll();
  }

  refreshAll(): void {
    for (const document of vscode.workspace.textDocuments) this.refresh(document);
  }

  refresh(document: vscode.TextDocument): void {
    this.context.guard(
      'diagnostics',
      () => {
        const scope = this.context.resolveScope(document);
        const text = scope === undefined ? undefined : document.getText();
        if (
          scope === undefined ||
          text === undefined ||
          text.length > MAXIMUM_MARKDOWN_SIZE_BYTES
        ) {
          this.collection.delete(document.uri);
          return;
        }
        const diagnostics: vscode.Diagnostic[] = [];
        for (const match of scanIds(text)) {
          if (scope.index.get(match.id) !== undefined) continue;
          const diagnostic = new vscode.Diagnostic(
            new vscode.Range(
              match.line,
              match.character,
              match.line,
              match.character + match.length,
            ),
            vscode.l10n.t(NAVIGATION_MESSAGES.unknownIdDiagnostic, match.id),
            vscode.DiagnosticSeverity.Warning,
          );
          diagnostic.source = 'Harness Navigator';
          diagnostics.push(diagnostic);
        }
        this.collection.set(document.uri, diagnostics);
      },
      undefined,
    );
  }

  dispose(): void {
    for (const subscription of this.subscriptions.splice(0)) subscription.dispose();
    this.collection.dispose();
  }
}
