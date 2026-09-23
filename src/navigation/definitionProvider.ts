import * as vscode from 'vscode';
import { idAtOffset } from './idMatcher';
import { toVscodeRange, type NavigationContext } from './harnessScope';

/** Definition/Peek/Ctrl+Click для известного Harness ID → canonical файл. */
export class HarnessDefinitionProvider implements vscode.DefinitionProvider {
  constructor(private readonly context: NavigationContext) {}

  provideDefinition(
    document: vscode.TextDocument,
    position: vscode.Position,
  ): vscode.LocationLink[] | undefined {
    return this.context.guard(
      'definition',
      () => {
        const scope = this.context.resolveScope(document);
        if (scope === undefined) return undefined;
        const line = document.lineAt(position.line);
        const hit = idAtOffset(line.text, position.character);
        if (hit === undefined) return undefined;
        const artifact = scope.index.get(hit.id);
        const definition = scope.index.definitionRangesOf(hit.id)[0];
        if (artifact === undefined) return undefined;
        const target =
          definition === undefined ? new vscode.Range(0, 0, 0, 0) : toVscodeRange(definition);
        return [
          {
            originSelectionRange: new vscode.Range(
              position.line,
              hit.start,
              position.line,
              hit.end,
            ),
            targetUri: vscode.Uri.file(artifact.file),
            targetRange: target,
            targetSelectionRange: target,
          },
        ];
      },
      undefined,
    );
  }
}
