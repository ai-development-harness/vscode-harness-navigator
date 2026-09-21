import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  createLifecycleRegistry,
  type SubscriptionSink,
} from '../../src/lifecycle/disposableRegistry';

function fakeSubscriptions(): SubscriptionSink & { items: { dispose(): void }[] } {
  const items: { dispose(): void }[] = [];
  return {
    items,
    push(...pushed) {
      items.push(...pushed);
      return items.length;
    },
  };
}

function trackedDisposable(log: string[], name: string, throwOnDispose = false) {
  return {
    dispose(): void {
      if (throwOnDispose) {
        log.push(`${name}:threw`);
        throw new Error(`${name} failed to dispose`);
      }
      log.push(name);
    },
  };
}

test('реестр один раз регистрируется в subscription sink, а дочерний disposable остаётся у реестра', () => {
  const subscriptions = fakeSubscriptions();
  const registry = createLifecycleRegistry(subscriptions);
  const log: string[] = [];

  const disposable = trackedDisposable(log, 'a');
  const returned = registry.register(disposable);

  assert.equal(returned, disposable);
  assert.equal(registry.count, 1);
  assert.equal(subscriptions.items.length, 1);
  assert.equal(subscriptions.items[0], registry);
});

test('dispose() освобождает каждый зарегистрированный disposable ровно один раз, в обратном порядке', () => {
  const subscriptions = fakeSubscriptions();
  const registry = createLifecycleRegistry(subscriptions);
  const log: string[] = [];

  registry.register(trackedDisposable(log, 'a'));
  registry.register(trackedDisposable(log, 'b'));
  registry.register(trackedDisposable(log, 'c'));

  assert.equal(registry.count, 3);
  assert.equal(registry.isDisposed, false);

  registry.dispose();

  assert.deepEqual(log, ['c', 'b', 'a']);
  assert.equal(registry.count, 0);
  assert.equal(registry.isDisposed, true);
});

test('dispose() идемпотентен: повторный вызов ничего не освобождает заново', () => {
  const subscriptions = fakeSubscriptions();
  const registry = createLifecycleRegistry(subscriptions);
  const log: string[] = [];

  registry.register(trackedDisposable(log, 'a'));
  registry.dispose();
  registry.dispose();

  assert.deepEqual(log, ['a']);
});

test('dispose() никогда не бросает исключение, даже если disposable бросает его, и освобождает остальные', () => {
  const subscriptions = fakeSubscriptions();
  const registry = createLifecycleRegistry(subscriptions);
  const log: string[] = [];

  registry.register(trackedDisposable(log, 'a'));
  registry.register(trackedDisposable(log, 'b', true));
  registry.register(trackedDisposable(log, 'c'));

  assert.doesNotThrow(() => {
    registry.dispose();
  });

  assert.deepEqual(log, ['c', 'b:threw', 'a']);
});
