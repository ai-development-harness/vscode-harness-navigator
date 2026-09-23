import * as vscode from 'vscode';
import { MAXIMUM_MARKDOWN_SIZE_BYTES } from '../projectModel/artifactIndex';
import { scanIds } from './idMatcher';
import type { NavigationContext } from './harnessScope';

export const HARNESS_TOKEN_TYPE = 'harnessArtifactId';
export const HARNESS_TOKEN_LEGEND = new vscode.SemanticTokensLegend([HARNESS_TOKEN_TYPE]);

/**
 * Точечные токены только для известных ID (один ID = один токен, без
 * перекрытия), чтобы не ухудшать Markdown highlighting. Цвет задаёт тема
 * через semanticTokenScopes; фиксированных RGB нет.
 */
export class HarnessSemanticTokensProvider
  implements vscode.DocumentSemanticTokensProvider, vscode.Disposable
{
  private readonly changeEmitter = new vscode.EventEmitter<void>();
  readonly onDidChangeSemanticTokens = this.changeEmitter.event;

  constructor(private readonly context: NavigationContext) {}

  fire(): void {
    this.changeEmitter.fire();
  }

  provideDocumentSemanticTokens(document: vscode.TextDocument): vscode.SemanticTokens {
    return this.context.guard(
      'semanticTokens',
      () => {
        const builder = new vscode.SemanticTokensBuilder(HARNESS_TOKEN_LEGEND);
        const scope = this.context.resolveScope(document);
        if (scope === undefined) return builder.build();
        const text = document.getText();
        if (text.length > MAXIMUM_MARKDOWN_SIZE_BYTES) return builder.build();
        for (const match of scanIds(text))
          if (scope.index.get(match.id) !== undefined)
            builder.push(match.line, match.character, match.length, 0, 0);
        return builder.build();
      },
      new vscode.SemanticTokens(new Uint32Array()),
    );
  }

  dispose(): void {
    this.changeEmitter.dispose();
  }
}
