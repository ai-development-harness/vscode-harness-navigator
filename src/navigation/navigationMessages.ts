/**
 * Localizable message templates navigation/relations providers. Модуль не
 * импортирует `vscode` (как `views/viewMessages.ts`), чтобы unit-тест мог
 * проверить покрытие l10n bundle без Extension Host.
 */
const MESSAGES = {
  hoverKind: 'Kind: {0}',
  hoverStatus: 'Status: {0}',
  hoverRelations: 'Outgoing relations: {0} · Incoming relations: {1} · Mentions: {2}',
  documentLinkTooltip: 'Open the Harness artifact {0}',
  unknownIdDiagnostic: 'The Harness identifier {0} was not found in this project.',
  noTarget: 'Place the cursor on a Harness identifier or select a Harness artifact.',
  unknownTarget: 'The Harness identifier {0} is not in this project.',
  referencesEmpty: 'No references to {0} were found.',
  relationsPlaceholder: 'Relations of {0}',
  relationsOutgoing: 'Outgoing relations',
  relationsIncoming: 'Incoming relations',
  relationsMentions: 'Mentions',
  relationsUnresolved: 'unresolved',
  relationsMentionCount: '{0} mention(s)',
  relationsFindAllReferences: 'Find All References',
  semanticTokenDescription: 'Harness artifact identifier',
} as const;

export const NAVIGATION_MESSAGES = MESSAGES;
export const NAVIGATION_MESSAGE_VALUES = Object.values(MESSAGES);
