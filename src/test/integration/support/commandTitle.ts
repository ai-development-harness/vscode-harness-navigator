import * as assert from 'node:assert/strict';

/**
 * Vscode-независимая проверка `title` из command contribution manifest.
 * Extension Host отдаёт title строкой либо, при установленном language pack,
 * объектом `{ value, original }`, где `value` — текст выбранной locale.
 * Нерезолвленный nls placeholder (`%key%`) фактическим title не считается.
 */

export type CommandTitleForm = 'string' | 'localized-object' | 'unknown';

const isLocalizedObject = (title: unknown): title is { value: string; original: unknown } =>
  typeof title === 'object' &&
  title !== null &&
  typeof (title as { value?: unknown }).value === 'string';

/** Форма title для Evidence-лога. */
export function describeCommandTitleForm(title: unknown): CommandTitleForm {
  if (typeof title === 'string') return 'string';
  if (isLocalizedObject(title)) return 'localized-object';
  return 'unknown';
}

/** Текст title выбранной locale; неизвестная форма даёт AssertionError, а не TypeError. */
export function commandTitleText(title: unknown): string {
  if (typeof title === 'string') return title;
  if (isLocalizedObject(title)) return title.value;
  assert.fail(`unexpected command title form: ${JSON.stringify(title)}`);
}

/** Title без запрещённого префикса и строго равен ожидаемому тексту locale. */
export function assertCommandTitle(
  title: unknown,
  expected: string,
  forbiddenPrefix: string,
): void {
  const text = commandTitleText(title);
  assert.ok(!text.startsWith(forbiddenPrefix), `title starts with "${forbiddenPrefix}": ${text}`);
  assert.equal(text, expected);
}
