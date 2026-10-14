# Розвідка — семьи + profit + expand

## C-пайплайн

1. **A — profit з локальної історії**: хто торкнувся пампу **до ATH** → seeds  
2. **B — expand**: Etherscan tokentx/native з цих адрес → нові edges у `data/graph/`  
3. Сімʼї / вікі / закономірності з оновленого графа  

## Команди

```bash
# тільки A (швидко)
PYTHONPATH=. .venv/bin/python -m rozvidka profit --no-expand

# A + B (N seeds × 4 chains — хвилини)
PYTHONPATH=. .venv/bin/python -m rozvidka profit --expand-limit 8

# повний оберт
PYTHONPATH=. .venv/bin/python -m rozvidka once --no-llm
PYTHONPATH=. .venv/bin/python -m rozvidka once --no-llm --no-expand
```

UI: http://127.0.0.1:8765/rozvidka.html  

Файли: `data/rozvidka/db/profit_seeds.json`, `addresses.json`, `families.json`
