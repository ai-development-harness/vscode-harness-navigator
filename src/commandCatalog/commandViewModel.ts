import type { CatalogCommand, CatalogDomain, CommandCatalog } from './commandGraph';
import { COMMAND_CATALOG_MESSAGES as M, COMMAND_DESCRIPTIONS } from './commandCatalogMessages';

/** Единственная нотация placeholder для команд с обязательным/необязательным вводом. */
export const INPUT_PLACEHOLDER = '<…>';
const STEP_TOKEN = 'STEP-NNN';

export type Translate = (message: string, ...args: (string | number)[]) => string;

export interface CommandGroup {
  readonly domain: string;
  readonly commands: readonly CatalogCommand[];
}

/** Группировка по domain в порядке графа. */
export function groupByDomain(catalog: CommandCatalog): CommandGroup[] {
  return catalog.domains.map((domain: CatalogDomain) => ({
    domain: domain.name,
    commands: domain.commands,
  }));
}

/** Команды, принимающие STEP target (для copy из STEP-узла). */
export function stepCommands(catalog: CommandCatalog): CatalogCommand[] {
  return catalog.commands.filter((command) => command.target === 'step');
}

/**
 * Текст для clipboard. Никогда не формирует shell-вызов. Правила:
 * (a) canonical берётся из графа как есть; (b) при `stepId` для target `step`
 * подставляется вместо токена `STEP-NNN`, а при его отсутствии дописывается в
 * конец; (c) `<…>` добавляется только к canonical, оканчивающемуся на `:`;
 * (d) остальное копируется без изменений.
 */
export function renderCommandTemplate(
  command: Pick<CatalogCommand, 'canonical' | 'target'>,
  options: { readonly stepId?: string } = {},
): string {
  const { canonical } = command;
  const { stepId } = options;
  if (command.target === 'step' && stepId !== undefined) {
    return canonical.includes(STEP_TOKEN)
      ? canonical.replace(STEP_TOKEN, stepId)
      : `${canonical} ${stepId}`;
  }
  return canonical.endsWith(':') ? `${canonical} ${INPUT_PLACEHOLDER}` : canonical;
}

/** Короткое описание: локализованная presentation-запись, иначе summary графа. */
export function commandDescription(command: CatalogCommand, t: Translate): string {
  const key = Object.hasOwn(COMMAND_DESCRIPTIONS, command.canonical)
    ? COMMAND_DESCRIPTIONS[command.canonical]
    : undefined;
  return key === undefined ? command.summary : t(key);
}

/** Plain-text tooltip из graph metadata (не Markdown). */
export function commandTooltip(command: CatalogCommand, t: Translate): string {
  const lines = [
    commandDescription(command, t),
    t(M.tooltipDomain, command.domain),
    t(M.tooltipTarget, command.target),
    t(M.tooltipInput, command.input),
  ];
  if (!command.chainAllowed) lines.push(t(M.tooltipChainNone));
  else if (command.outgoing.length === 0) lines.push(t(M.tooltipChainAllowed));
  else lines.push(t(M.tooltipChainNext, nextCommands(command)));
  if (command.dispatchKind !== '') lines.push(t(M.tooltipDispatch, command.dispatchKind));
  if (command.documentation !== '') lines.push(t(M.tooltipDocumentation, command.documentation));
  return lines.filter((line) => line !== '').join('\n');
}

function nextCommands(command: CatalogCommand): string {
  const targets = new Set(command.outgoing.map((transition) => transition.to));
  return [...targets].map((operation) => `${command.domain} ${operation}`).join(', ');
}

/** `domain · target/input` для detail в Find Command. */
export function commandDetail(command: CatalogCommand): string {
  return `${command.domain} · ${command.target}/${command.input}`;
}

export type CatalogKind = 'ready' | 'readError' | 'unsupportedSchema';

/**
 * Сообщение `TreeView.message` по состояниям каталогов valid roots.
 * Пустая строка — сообщение не нужно. Содержимое файла графа не утекает.
 */
export function computeCommandsMessage(
  states: readonly { readonly kind: CatalogKind; readonly commandCount: number }[],
  t: Translate,
  noHarnessProject: string,
): string {
  if (states.length === 0) return t(noHarnessProject);
  const ready = states.filter((state) => state.kind === 'ready');
  if (ready.length > 0)
    return ready.some((state) => state.commandCount > 0) ? '' : t(M.viewNoCommands);
  return states.some((state) => state.kind === 'unsupportedSchema')
    ? t(M.viewGraphUnsupported)
    : t(M.viewGraphUnavailable);
}
