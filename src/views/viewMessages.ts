/**
 * Localizable message templates, используемые Artifacts View, Focus View и
 * `Harness: Go to Artifact`. Модуль намеренно не импортирует `vscode` во
 * время выполнения (см. `artifactViewModel.ts`), чтобы `tests/unit/*` мог
 * проверять покрытие `l10n` bundle этими ключами без Extension Host — тот
 * же паттерн, что `MESSAGES`/`ARTIFACT_DIAGNOSTIC_MESSAGES` в
 * `projectModel/artifactIndex.ts`. Значения передаются в `vscode.l10n.t(...)`
 * из view-модулей, которые уже зависят от `vscode`.
 */
const MESSAGES = {
  noHarnessProject: 'No Harness project was detected in this workspace.',
  noArtifacts: 'This Harness project does not contain any artifacts yet.',
  // Намеренно не называет конкретную команду по имени (F-004 STEP REVIEW
  // STEP-004): RU-перевод команды `Harness: Clear Filters` в
  // `package.nls.ru.json` — «Harness: Очистить фильтры», не буквальный
  // перевод английского canonical title, поэтому hardcoded EN-имя команды
  // внутри переводимого текста вело бы RU-пользователя в никуда.
  filteredEmpty: 'No artifacts match the active filter. Clear the active filter to see them all.',
  statusTooltip: 'Status: {0}',
  openArtifact: 'Open Harness artifact',
  focusEmpty: 'There are no in-progress or blocked STEP artifacts, and no open OQ artifacts.',
  focusActiveGroup: 'Active STEP',
  focusBlockedGroup: 'Blocked STEP',
  focusOpenQuestionsGroup: 'Open OQ',
  goToArtifactPlaceholder: 'Go to a Harness artifact by ID, title or kind',
  goToArtifactEmpty: 'No Harness artifacts were found in this workspace.',
  sortOrderPlaceholder: 'Select the sort order for the Harness Artifacts view',
  sortOrderId: 'ID',
  sortOrderTitle: 'Title',
  sortOrderStatus: 'Status',
  sortOrderPriority: 'Priority',
  filterFieldPlaceholder: 'Select a filter field for the Harness Artifacts view',
  filterFieldStatus: 'Status',
  filterFieldType: 'Type',
  filterFieldPriority: 'Priority',
  filterFieldPhase: 'Phase',
  filterValuePlaceholder: 'Select a value for {0}',
  filterClearOption: 'Any (clear this filter)',
  statusBarText: 'Harness · {0} active · {1} blocked · {2} OQ',
  statusBarTextCategory: 'Harness · {0}',
  statusBarTooltipRootCategory: '{0}: {1}',
  statusBarName: 'Harness Navigator summary',
  statusBarTooltipRoot:
    '{0}: release {1}, {2} STEP, {3} REQ, {4} ADR, {5} open OQ, {6} diagnostics',
  statusBarTooltipHint: 'Click to open the Harness Navigator view.',
  summaryRelease: 'Harness release',
  summaryOpenQuestions: 'Open OQ',
  summaryInProgress: 'In progress',
  summaryBlocked: 'Blocked',
  summaryDiagnostics: 'Diagnostics',
  filterPhaseInputPrompt: 'Enter the STEP phase to filter by, or leave empty to clear it',
} as const;

export const VIEW_MESSAGES = MESSAGES;
export const VIEW_MESSAGE_VALUES = Object.values(MESSAGES);
