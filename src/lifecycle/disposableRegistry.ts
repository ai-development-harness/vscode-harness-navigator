import type { Disposable } from 'vscode';

/**
 * Минимальное подмножество `vscode.ExtensionContext.subscriptions`,
 * необходимое реестру. Оставлено узким, чтобы реестр можно было
 * unit-тестировать без реального VS Code runtime.
 */
export interface SubscriptionSink {
  push(...items: Disposable[]): number;
}

/**
 * Внутренний lifecycle-реестр: каждый disposable, созданный этим
 * расширением, проходит через `register` и отслеживается локально. Сам
 * реестр один раз добавляется во владеющий `ExtensionContext.subscriptions`:
 * это оставляет единственного владельца disposal каждого дочернего объекта
 * и предотвращает двойной вызов `dispose()` со стороны Extension Host.
 * Реестр дополнительно даёт:
 *
 * - количество регистраций было напрямую наблюдаемым (`count`), и
 * - `dispose()` можно было безопасно вызывать более одного раза — из
 *   тестов или из defensive `deactivate()` — без исключений и без
 *   повторного disposal уже освобождённого элемента.
 */
export class LifecycleRegistry implements Disposable {
  private readonly disposables: Disposable[] = [];
  private disposed = false;

  constructor(subscriptions: SubscriptionSink) {
    subscriptions.push(this);
  }

  /**
   * Регистрирует disposable только в этом реестре. Сам реестр уже связан с
   * `ExtensionContext.subscriptions`, поэтому Extension Host освобождает
   * дочерние disposable через единственный жизненный цикл без дублей.
   * Возвращает тот же disposable, чтобы сохранить ссылку одним выражением.
   */
  register<T extends Disposable>(disposable: T): T {
    this.disposables.push(disposable);
    return disposable;
  }

  /** Количество disposable-объектов, которые сейчас отслеживает реестр. */
  get count(): number {
    return this.disposables.length;
  }

  /** Был ли уже выполнен `dispose()`. */
  get isDisposed(): boolean {
    return this.disposed;
  }

  /**
   * Освобождает каждый зарегистрированный disposable в обратном порядке
   * регистрации. Идемпотентен: повторный вызов ничего не делает.
   * Исключение из одного disposable не мешает освободить остальные, а
   * сама ошибка проглатывается, потому что деактивация расширения не
   * должна бросать исключения.
   */
  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;

    const pending = this.disposables.splice(0, this.disposables.length);
    for (const disposable of pending.reverse()) {
      try {
        disposable.dispose();
      } catch {
        // Деактивация не должна бросать исключения; неисправный disposable
        // не должен блокировать освобождение остальных.
      }
    }
  }
}

/** Создаёт {@link LifecycleRegistry}, привязанный к переданному subscription sink. */
export function createLifecycleRegistry(subscriptions: SubscriptionSink): LifecycleRegistry {
  return new LifecycleRegistry(subscriptions);
}
