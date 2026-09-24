import type { ProjectDiagnostic } from '../projectModel/projectState';

/**
 * Localizable message templates Command Catalog (diagnostics, Commands View,
 * Find/Copy Command). Модуль не импортирует `vscode` (паттерн
 * `views/viewMessages.ts`), чтобы unit-тест проверял покрытие l10n bundle
 * без Extension Host.
 */
const MESSAGES = {
  graphReadError: 'The Harness command graph cannot be read.',
  graphUnsupportedSchema: 'The Harness command graph schema is not supported: {0}.',
  viewGraphUnavailable:
    'The Harness command graph is unavailable. Open the Harness diagnostics for details.',
  viewGraphUnsupported:
    'The Harness command graph schema is not supported. Open the Harness diagnostics for details.',
  viewGraphErrorDescription: 'unavailable',
  viewNoCommands: 'The Harness command graph does not contain any commands.',
  tooltipDomain: 'Domain: {0}',
  tooltipTarget: 'Target: {0}',
  tooltipInput: 'Input: {0}',
  tooltipChainNone: 'Chain: not allowed',
  tooltipChainAllowed: 'Chain: allowed',
  tooltipChainNext: 'Chain: allowed, next: {0}',
  tooltipDispatch: 'Dispatch: {0}',
  tooltipDocumentation: 'Documentation: {0}',
  findPlaceholder: 'Find a Harness command to copy to the clipboard',
  findEmpty: 'No Harness commands are available in this workspace.',
  copied: 'Copied to the clipboard: {0}',
  copyFailed: 'The command could not be copied to the clipboard.',
  copyPickStepCommand: 'Select a command to copy for {0}',
  copyNotStep: 'Select a STEP artifact to copy a STEP command.',
  copyNoStepCommands: 'The Harness command graph has no commands that take a STEP target.',
  docNone: 'This Harness command has no documentation reference.',
  docBlocked:
    'The documentation reference of this command is outside the project and was not opened.',
  docNotFound: 'The documentation file was not found: {0}',
} as const;

export const COMMAND_CATALOG_MESSAGES = MESSAGES;
export const COMMAND_CATALOG_MESSAGE_VALUES = Object.values(MESSAGES);

/**
 * Presentation-only короткие описания команд: canonical → английский текст,
 * служащий ключом `vscode.l10n.t`. Это НЕ источник каталога (команды, target,
 * input и chain берутся из command graph); наличие записи лишь выбирает
 * локализованное описание вместо fallback на `summary` графа.
 */
export const COMMAND_DESCRIPTIONS: Readonly<Record<string, string>> = {
  'PROJECT INIT': 'Initialize a Harness project from the local project brief',
  'PROJECT STATUS': 'Show the project state and available work',
  'PROJECT RECONCILE': 'Reconcile project artifacts with the repository',
  'PROJECT QUICK FIX:': 'Make a small safe change without a separate task',
  'STEP ADD:': 'Create a new task from a short description',
  'STEP LIST': 'List tasks and their states',
  'STEP SHOW STEP-NNN': 'Show one task',
  'STEP NEXT': 'Suggest the next available task',
  'STEP PLAN STEP-NNN': 'Prepare the implementation plan of a task',
  'STEP IMPLEMENT STEP-NNN': 'Implement an approved task plan',
  'STEP REVIEW STEP-NNN': 'Independently review a task implementation',
  'STEP FIX STEP-NNN': 'Fix review findings of a task',
  'STEP RUN STEP-NNN': 'Run the full task cycle',
  'STEP AUDIT STEP-NNN': 'Audit a completed task',
  'SKILL FIND:': 'Search for a skill by description',
  'SKILL INSTALL:': 'Install a skill from a source',
  'SKILL CREATE:': 'Create a new project skill',
  'GITHUB GENERATE TEMPLATES': 'Generate GitHub issue and pull request templates',
  'RELEASE CHECK': 'Check release readiness',
  'HARNESS HELP': 'Show the Harness command help',
  'HARNESS UPDATE CHECK': 'Check for a Harness protocol update',
  'HARNESS UPDATE APPLY': 'Apply a checked Harness protocol update',
  'HARNESS STATUS': 'Show the Harness state and pending execution',
  'HARNESS RESUME': 'Resume an interrupted execution',
  'HARNESS DOCTOR': 'Diagnose the Harness installation',
  'HARNESS CONFIG': 'Show the effective Harness configuration',
  'GIT CHECK': 'Check the repository before a Git operation',
  'GIT COMMIT': 'Prepare a commit of the current changes',
  'GIT PUSH': 'Push the current branch',
  'GIT PR': 'Prepare a pull request',
  'GIT PR FINISH': 'Finish a merged pull request locally',
  'GIT SYNC': 'Synchronize the local branch with the remote',
};

export const COMMAND_DESCRIPTION_VALUES = Object.values(COMMAND_DESCRIPTIONS);

export type CatalogDiagnosticCategory = Extract<
  ProjectDiagnostic['category'],
  'CommandGraphReadError' | 'CommandGraphUnsupportedSchema'
>;

/**
 * Diagnostic без содержимого файла графа: detail — только фиксированный
 * технический маркер причины, не текст из недоверенного JSON.
 */
export function catalogDiagnostic(
  category: CatalogDiagnosticCategory,
  message: string,
  args: readonly (string | number)[] = [],
  detail = '',
): ProjectDiagnostic {
  return { category, message, messageArguments: args, detail };
}
