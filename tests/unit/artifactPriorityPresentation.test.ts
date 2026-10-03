import assert from 'node:assert/strict';
import test from 'node:test';
import { artifactPriorityPresentation } from '../../src/views/artifactPriorityPresentation';

test('artifactPriorityPresentation возвращает canonical badge, ThemeColor id и label', () => {
  assert.deepEqual(artifactPriorityPresentation('critical'), {
    badge: '!',
    colorId: 'editorError.foreground',
    label: 'Critical',
  });
  assert.deepEqual(artifactPriorityPresentation('high'), {
    badge: 'H',
    colorId: 'editorWarning.foreground',
    label: 'High',
  });
  assert.deepEqual(artifactPriorityPresentation('medium'), {
    badge: 'M',
    colorId: 'editorInfo.foreground',
    label: 'Medium',
  });
  assert.deepEqual(artifactPriorityPresentation('low'), {
    badge: 'L',
    colorId: 'disabledForeground',
    label: 'Low',
  });
});

test('artifactPriorityPresentation fail-safe отклоняет отсутствующие, неизвестные и prototype значения', () => {
  for (const value of [undefined, null, '', 'urgent', 'toString', 'constructor', 1]) {
    assert.equal(artifactPriorityPresentation(value), undefined, String(value));
  }
});
