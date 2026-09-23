import * as vscode from 'vscode';
import { completionPrefixAt } from './idMatcher';
import type { NavigationContext } from './harnessScope';
import { buildCompletionModels } from './navigationViewModel';

/** Completion вставляет только canonical ID; список из индекса (Map lookup). */
export class HarnessCompletionProvider implements vscode.CompletionItemProvider {
  constructor(private readonly context: NavigationContext) {}

  provideCompletionItems(
    document: vscode.TextDocument,
    position: vscode.Position,
  ): vscode.CompletionItem[] {
    return this.context.guard(
      'completion',
      () => {
        const scope = this.context.resolveScope(document);
        if (scope === undefined) return [];
        const linePrefix = document.lineAt(position.line).text.slice(0, position.character);
        const typed = completionPrefixAt(linePrefix);
        if (typed === undefined) return [];
        const range = new vscode.Range(
          position.line,
          typed.start,
          position.line,
          position.character,
        );
        return buildCompletionModels(
          scope.index.artifactIds(),
          (id) => scope.index.get(id),
          typed.prefix,
        ).map((model) => {
          const item = new vscode.CompletionItem(model.id, vscode.CompletionItemKind.Reference);
          item.detail = model.detail;
          item.documentation = new vscode.MarkdownString().appendText(model.title);
          item.insertText = model.id;
          item.filterText = model.id;
          item.range = range;
          return item;
        });
      },
      [],
    );
  }
}
