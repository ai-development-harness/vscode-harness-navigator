# Reviews

Каждый `STEP REVIEW STEP-NNN` создаёт новый immutable report в каталоге `planning/reviews/STEP-NNN/`.

Нельзя переписывать старый FAIL report после исправления; повторный review создаёт новый файл. STEP не хранит mutable cache latest report/verdict: актуальный результат выводится из immutable review history.
