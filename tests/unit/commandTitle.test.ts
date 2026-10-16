import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  assertCommandTitle,
  commandTitleText,
  describeCommandTitleForm,
} from '../../src/test/integration/support/commandTitle';

const EN = 'Open Documentation';
const RU = 'Открыть документацию';
const localized = (value: string) => ({ value, original: EN });

const fails = (fn: () => void) => assert.throws(fn, assert.AssertionError);

test('строковый title EN и RU проходит проверку', () => {
  assertCommandTitle(EN, EN, 'Harness');
  assertCommandTitle(RU, RU, 'Harness');
});

test('объектный локализованный title проверяется по value', () => {
  assertCommandTitle(localized(RU), RU, 'Harness');
  assert.equal(commandTitleText(localized(RU)), RU);
});

test('неверный текст падает в строковой и объектной форме', () => {
  fails(() => assertCommandTitle(EN, RU, 'Harness'));
  fails(() => assertCommandTitle(localized(EN), RU, 'Harness'));
});

test('запрещённый префикс падает в строковой и объектной форме', () => {
  fails(() => assertCommandTitle(`Harness: ${RU}`, `Harness: ${RU}`, 'Harness'));
  fails(() => assertCommandTitle(localized(`Harness: ${RU}`), `Harness: ${RU}`, 'Harness'));
});

test('нерезолвленный nls placeholder не принимается', () => {
  fails(() => assertCommandTitle('%command.openCommandDocumentation.title%', EN, 'Harness'));
});

test('неизвестная форма даёт AssertionError, а не TypeError', () => {
  for (const title of [null, undefined, 42, {}, { value: 1, original: EN }]) {
    fails(() => assertCommandTitle(title, EN, 'Harness'));
  }
});

test('describeCommandTitleForm различает формы', () => {
  assert.equal(describeCommandTitleForm(EN), 'string');
  assert.equal(describeCommandTitleForm(localized(RU)), 'localized-object');
  assert.equal(describeCommandTitleForm(null), 'unknown');
  assert.equal(describeCommandTitleForm({ original: EN }), 'unknown');
});
