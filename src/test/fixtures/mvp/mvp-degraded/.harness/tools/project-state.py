# Контролируемый ответ fixture: настоящий fixed API entry point без записи workspace.
import pathlib
import sys
import json

response = pathlib.Path('.harness/project-state-fixture.json').read_text(encoding='utf-8')
sys.stdout.write(response)
# Как реальный Harness API, BLOCKED сопровождается nonzero exit.
try:
    blocked = json.loads(response).get('status') == 'BLOCKED'
except json.JSONDecodeError:
    blocked = False
sys.exit(1 if blocked else 0)
