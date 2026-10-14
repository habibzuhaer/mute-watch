# Intel — multi-chain families / pre-pump (hybrid)

## EN

New package `intel/` beside MUTE poll + `pump_prep` graph.

- **BNB**: Etherscan V2 `chainid=56` — tokentx + native, expand neighbors  
- **Solana**: Helius/RPC — SOL+SPL **IN/OUT** with counterparties  
- **EVM adapter**: imports `data/graph` + watchlists + rozvidka profit seeds into queues  
- **Families**: ≥1 transfer link (Union-Find), tags in address DB  
- **Detectors**: activity spikes + pre-pump (before ATH from legacy tokens)  
- **Collect**: designed for **12h × N** runs (`./scripts/start_intel.sh`)

```bash
PYTHONPATH=. .venv/bin/python -m intel bootstrap
PYTHONPATH=. .venv/bin/python -m intel once
./scripts/start_intel.sh          # 12h collect
INTEL_COLLECT_HOURS=12 ./scripts/start_intel.sh
./scripts/stop_intel.sh
```

## Durable cycles / стійкі цикли

- Checkpoint: `in_flight` → on crash requeued; session `collect_until` resumed  
- Journal: `data/intel/cycles.jsonl`  
- Stop marks `interrupted`; next `./scripts/start_intel.sh` resumes  
- UI tabs: Cycles · Families · Signals · Queue — http://127.0.0.1:8765/intel.html  
- Panel: Agents card on dashboard Cycles section  

```bash
./scripts/start_intel.sh          # resume by default
INTEL_FRESH=1 ./scripts/start_intel.sh   # new 12h window
./scripts/stop_intel.sh           # checkpoint + interrupt
```


---

## UK

Новий пакет `intel/` поруч із MUTE poll і графом `pump_prep`.

- **BNB**: Etherscan V2 — токен + native, expand сусідів  
- **Solana**: Helius/RPC — SOL+SPL **IN/OUT** з контрагентами  
- **Адаптер EVM**: тягне `data/graph` + watchlist + profit seeds у чергу  
- **Сімʼї**: ≥1 переказ → компонент; мітки в БД адрес  
- **Детектори**: спайки активності + пре-памп (до ATH)  
- **Збір**: під **12 год × N** прогонів

```bash
PYTHONPATH=. .venv/bin/python -m intel bootstrap
PYTHONPATH=. .venv/bin/python -m intel once
./scripts/start_intel.sh
```

UI: http://127.0.0.1:8765/intel.html  

Дані: `data/intel/`  

Пізніше: Solana ATH, Dex API, крос-чейн мости.
