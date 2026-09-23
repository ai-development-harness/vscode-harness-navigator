import { test } from 'node:test';
import assert from 'node:assert/strict';
import { completionPrefixAt, idAtOffset, scanIds } from '../../src/navigation/idMatcher';

test('idAtOffset учитывает границы слова и пунктуацию', () => {
  const text = 'См. (REQ-001), STEP-12.';
  assert.deepEqual(idAtOffset(text, 6), { id: 'REQ-001', start: 5, end: 12 });
  assert.equal(idAtOffset(text, 12)?.id, 'REQ-001');
  assert.equal(idAtOffset(text, 13), undefined);
  assert.equal(idAtOffset(text, 20)?.id, 'STEP-12');
  assert.equal(idAtOffset(text, 0), undefined);
});

test('неизвестные и некорректные ID не совпадают', () => {
  for (const text of ['STEP-', 'STEP-abc', 'XSTEP-1', 'STEP-1abc', 'REQ_001'])
    assert.equal(idAtOffset(text, 2), undefined, text);
});

test('scanIds возвращает позиции для LF и CRLF', () => {
  assert.deepEqual(
    scanIds('a REQ-1\r\nADR-22 OQ-3\n').map((m) => [m.id, m.line, m.character, m.length]),
    [
      ['REQ-1', 0, 2, 5],
      ['ADR-22', 1, 0, 6],
      ['OQ-3', 1, 7, 4],
    ],
  );
});

test('completionPrefixAt распознаёт префиксы STEP-/REQ-/ADR-/OQ-', () => {
  assert.deepEqual(completionPrefixAt('см. STEP-'), { prefix: 'STEP-', start: 4 });
  assert.deepEqual(completionPrefixAt('REQ-00'), { prefix: 'REQ-00', start: 0 });
  assert.equal(completionPrefixAt('ADR-1')?.prefix, 'ADR-1');
  assert.equal(completionPrefixAt('(OQ-')?.prefix, 'OQ-');
  assert.equal(completionPrefixAt('XSTEP-'), undefined);
  assert.equal(completionPrefixAt('STEP'), undefined);
  assert.equal(completionPrefixAt('STEP-1 '), undefined);
});
