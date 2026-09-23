import path from 'node:path';
import { readContainedMarkdown } from '../projectModel/artifactIndex';
import type { ProjectDiagnostic } from '../projectModel/projectState';
import { COMMAND_CATALOG_MESSAGES, catalogDiagnostic } from './commandCatalogMessages';

/**
 * Единственная точка знания о расположении command graph. Это фиксированный
 * protocol path Harness (REQ-007/ADR-003), а не ручной список команд и не
 * configured path манифеста.
 */
export const COMMAND_GRAPH_RELATIVE_PATH = '.harness/command-transitions.json';
export const SUPPORTED_SCHEMA_VERSIONS: readonly number[] = [1];

export interface CommandTransition {
  /** Операция-источник (ключ команды внутри домена). */
  readonly from: string;
  /** Операция-приёмник (ключ команды внутри домена). */
  readonly to: string;
  readonly onPreviousResult: readonly string[];
  readonly runtimePreconditions: readonly string[];
}

export interface CatalogCommand {
  readonly canonical: string;
  readonly domain: string;
  /** Ключ команды в графе (например `PLAN`, `UPDATE CHECK`). */
  readonly operation: string;
  /** `none`/`step`/`release-optional` либо будущее значение как строка. */
  readonly target: string;
  /** `none`/`required`/`optional` либо будущее значение как строка. */
  readonly input: string;
  readonly chainAllowed: boolean;
  readonly summary: string;
  readonly documentation: string;
  readonly dispatchKind: string;
  readonly outgoing: readonly CommandTransition[];
  readonly incoming: readonly CommandTransition[];
}

export interface CatalogDomain {
  readonly name: string;
  readonly chainEnabled: boolean;
  readonly inheritTarget: boolean;
  readonly continuationAliases: Readonly<Record<string, string>>;
  readonly transitions: readonly CommandTransition[];
  readonly commands: readonly CatalogCommand[];
}

export interface CommandCatalog {
  readonly domains: readonly CatalogDomain[];
  readonly commands: readonly CatalogCommand[];
  /** Malformed записи, пропущенные без падения каталога (только имена). */
  readonly skipped: readonly string[];
}

export type ParsedCommandGraph =
  | { readonly kind: 'ready'; readonly catalog: CommandCatalog }
  | { readonly kind: 'unsupportedSchema'; readonly schema: string }
  | { readonly kind: 'readError' };

export type CatalogState =
  | {
      readonly kind: 'ready';
      readonly catalog: CommandCatalog;
      readonly diagnostics: readonly ProjectDiagnostic[];
    }
  | {
      readonly kind: 'readError' | 'unsupportedSchema';
      readonly diagnostics: readonly ProjectDiagnostic[];
    };

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : [];
}

function parseTransitions(value: unknown): CommandTransition[] {
  if (!Array.isArray(value)) return [];
  const transitions: CommandTransition[] = [];
  for (const item of value) {
    if (!isRecord(item) || typeof item.from !== 'string' || typeof item.to !== 'string') continue;
    transitions.push({
      from: item.from,
      to: item.to,
      onPreviousResult: stringArray(item.onPreviousResult),
      runtimePreconditions: stringArray(item.runtimePreconditions),
    });
  }
  return transitions;
}

function parseCommand(
  domain: string,
  operation: string,
  value: unknown,
  transitions: readonly CommandTransition[],
): CatalogCommand | undefined {
  if (!isRecord(value)) return undefined;
  const { canonical, target, input, chainAllowed } = value;
  if (
    typeof canonical !== 'string' ||
    canonical.trim() === '' ||
    typeof target !== 'string' ||
    typeof input !== 'string' ||
    typeof chainAllowed !== 'boolean'
  )
    return undefined;
  const dispatch = isRecord(value.dispatch) ? value.dispatch : {};
  return {
    canonical,
    domain,
    operation,
    target,
    input,
    chainAllowed,
    summary: typeof value.summary === 'string' ? value.summary : '',
    documentation: typeof value.documentation === 'string' ? value.documentation : '',
    dispatchKind: typeof dispatch.kind === 'string' ? dispatch.kind : '',
    outgoing: transitions.filter((transition) => transition.from === operation),
    incoming: transitions.filter((transition) => transition.to === operation),
  };
}

function parseDomain(name: string, value: unknown, skipped: string[]): CatalogDomain | undefined {
  if (!isRecord(value) || !isRecord(value.commands)) return undefined;
  const transitions = parseTransitions(value.transitions);
  const aliases: Record<string, string> = {};
  if (isRecord(value.continuationAliases))
    for (const [alias, target] of Object.entries(value.continuationAliases))
      if (typeof target === 'string') aliases[alias] = target;
  const commands: CatalogCommand[] = [];
  for (const [operation, raw] of Object.entries(value.commands)) {
    const command = parseCommand(name, operation, raw, transitions);
    if (command === undefined) skipped.push(`${name}/${operation}`);
    else commands.push(command);
  }
  return {
    name,
    chainEnabled: value.chainEnabled === true,
    inheritTarget: value.inheritTarget === true,
    continuationAliases: aliases,
    transitions,
    commands,
  };
}

/**
 * Fail-safe разбор недоверенного JSON: без eval/exec, проверка типов на каждом
 * уровне, лишние поля и `reasoning` игнорируются. Неподдерживаемый или
 * отсутствующий `schemaVersion` не интерпретируется эвристически.
 */
export function parseCommandGraph(text: string): ParsedCommandGraph {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { kind: 'readError' };
  }
  if (!isRecord(parsed)) return { kind: 'readError' };
  const version = parsed.schemaVersion;
  if (typeof version !== 'number' || !SUPPORTED_SCHEMA_VERSIONS.includes(version))
    return {
      kind: 'unsupportedSchema',
      schema:
        typeof version === 'number' || typeof version === 'string'
          ? String(version).slice(0, 32)
          : 'missing',
    };
  if (!isRecord(parsed.domains)) return { kind: 'readError' };
  const skipped: string[] = [];
  const domains: CatalogDomain[] = [];
  for (const [name, raw] of Object.entries(parsed.domains)) {
    const domain = parseDomain(name, raw, skipped);
    if (domain === undefined) skipped.push(name);
    else domains.push(domain);
  }
  return {
    kind: 'ready',
    catalog: { domains, commands: domains.flatMap((domain) => domain.commands), skipped },
  };
}

/**
 * Читает и разбирает граф одного valid root. Чтение идёт через существующий
 * contained reader (containment, symlink, размер); любая ошибка I/O даёт
 * изолированное `readError` состояние, а не исключение.
 */
export function loadCatalogForRoot(root: string): CatalogState {
  let text: string;
  try {
    text = readContainedMarkdown(root, path.join(root, COMMAND_GRAPH_RELATIVE_PATH));
  } catch {
    return readErrorState();
  }
  const parsed = parseCommandGraph(text);
  switch (parsed.kind) {
    case 'ready':
      return { kind: 'ready', catalog: parsed.catalog, diagnostics: [] };
    case 'unsupportedSchema':
      return {
        kind: 'unsupportedSchema',
        diagnostics: [
          catalogDiagnostic(
            'CommandGraphUnsupportedSchema',
            COMMAND_CATALOG_MESSAGES.graphUnsupportedSchema,
            [parsed.schema],
          ),
        ],
      };
    case 'readError':
      return readErrorState();
  }
}

function readErrorState(): CatalogState {
  return {
    kind: 'readError',
    diagnostics: [
      catalogDiagnostic('CommandGraphReadError', COMMAND_CATALOG_MESSAGES.graphReadError),
    ],
  };
}
