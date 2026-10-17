# Замеры hardening self-test для #363

На синтетическом downstream checkout из 1943 файлов (22 428 708 байт) медиана
полного instrumented hardening main уменьшилась с 119,208 до 51,891 секунды
(56,47%). Лимит runner остаётся 120 секунд. Во всех шести итоговых запусках
сохранены 55 вызовов полного validator: 20 ожидаемых успехов и 35 ожидаемых
отказов, с одинаковой последовательностью mode/exitCode.

| Серия | Запуск 1, с | Запуск 2, с | Запуск 3, с | Медиана, с |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 118,704 | 119,208 | 119,236 | 119,208 |
| Candidate | 51,982 | 51,891 | 51,696 | 51,891 |

Обе стороны содержали одинаковые 1528 product files. После изоляции baseline
fixture содержала 1962 файла и 22 980 890 байт, candidate — 420 файлов и
4 627 206 байт; эти числа включают созданные при подготовке файлы. Уменьшена
только синтетическая fixture данного теста. Основная проверка consumer checkout
и остальные сценарии runner не используют сокращённый набор.

Среда: Linux x86_64, Python 3.12.3. Это локальное сравнение времени теста,
а не обещание времени на любом CI runner. Python 3.11/3.13 и Windows проверяются
отдельными CI lanes. Первичные три пары чередовались; после исправления
configured paths финальный candidate измерен ещё три раза. Поэтому итоговый
benchmark gate содержит честное предупреждение `NON_INTERLEAVED_RUNS`.
Промежуточные candidate measurements в итоговую таблицу не включены.

`baseline-*.json` и `candidate-*.json` — нормализованные captured numeric traces,
а не восстановленные terminal quotes. `measure.py.txt` хранит точные байты
измерительной обёртки. `metadata.json` фиксирует среду, payload, исходный SHA,
деревья disposable fixtures и хеши трёх performance components; эти компоненты
совпадают с публикуемой реализацией. Измеренный candidate snapshot предшествует
финальным правкам output contract и документации. Release qualification проверяет
полный итоговый snapshot и затем точный merged SHA отдельно.

Воспроизведение из корня upstream repository:

```bash
python3 .harness/docs/evidence/issue-363/reproduce.py
python3 .harness/docs/evidence/issue-363/reproduce.py --run
python3 .harness/tools/benchmark-methodology.py --evidence-file .harness/docs/evidence/issue-363/benchmark-evidence.json --json
```

Первая команда восстанавливает обе fixtures во временном каталоге и сверяет
точные Git trees. Вторая дополнительно выполняет три пары замеров. Исходники
baseline берутся из сохранённого sourceRevision, candidate восстанавливается
через captured snapshot diff; реальный consumer checkout не изменяется.
Третья команда проверяет сохранённое evidence: результат `PASS`, наблюдаемая
вариация не превышает 0,56%, минимальный заявленный эффект — 20%.
