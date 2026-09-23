/**
 * vscode-независимое распознавание Harness ID. Единый regex совпадает с тем,
 * который использует Reference Index (`STEP|REQ|ADR|OQ-\d+`), чтобы providers
 * и индекс не расходились в границах ID.
 */
const ID_SOURCE = '\\b(?:STEP|REQ|ADR|OQ)-\\d+\\b';

export interface IdMatch {
  readonly id: string;
  /** 0-based line. */
  readonly line: number;
  /** 0-based начало ID в строке. */
  readonly character: number;
  readonly length: number;
}

/**
 * Возвращает ID под курсором в тексте одной строки. Конец ID включается
 * (курсор сразу после последней цифры), как у стандартного word-lookup.
 * Работает по тексту документа, а не индекса: актуально для несохранённых правок.
 */
export function idAtOffset(
  lineText: string,
  offset: number,
): { readonly id: string; readonly start: number; readonly end: number } | undefined {
  for (const match of lineText.matchAll(new RegExp(ID_SOURCE, 'gu'))) {
    const start = match.index;
    const end = start + match[0].length;
    if (offset >= start && offset <= end) return { id: match[0], start, end };
    if (start > offset) break;
  }
  return undefined;
}

/** Все ID текста с позициями line/character (CRLF и LF). */
export function scanIds(text: string): IdMatch[] {
  const result: IdMatch[] = [];
  const lines = text.split(/\r?\n/u);
  for (let line = 0; line < lines.length; line += 1) {
    for (const match of (lines[line] as string).matchAll(new RegExp(ID_SOURCE, 'gu')))
      result.push({ id: match[0], line, character: match.index, length: match[0].length });
  }
  return result;
}

/**
 * Префикс completion перед курсором: `STEP-`, `REQ-0`, `ADR-1`, `OQ-`.
 * Возвращает набранный текст и его начало в строке.
 */
export function completionPrefixAt(
  linePrefix: string,
): { readonly prefix: string; readonly start: number } | undefined {
  const match = /(?<![\w-])(?:STEP|REQ|ADR|OQ)-\d*$/u.exec(linePrefix);
  return match === null ? undefined : { prefix: match[0], start: match.index };
}
