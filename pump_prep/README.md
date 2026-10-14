# pump_prep — early pump preparation scanner

Offline EVM scanner: seed MM / wash-shop wallets → token transfers → prep signals + address graph → HTML.

## Run

```bash
# needs ETHERSCAN_API_KEY in MUTE/.env
cd /path/to/MUTE
python -m pump_prep run
# optional:
python -m pump_prep run --days 14 --no-expand
```

Output:

- `pump_prep/out/pump_prep_report.html` — signals, addresses, edges (filters)
- `pump_prep/out/pump_prep_data.json` — raw payload

## Live Telegram (MUTE)

```bash
chmod +x scripts/start_prep.sh
./scripts/start_prep.sh
```

Uses `addresses/pump_prep_watchlist.json`, `ALERT_MODE=prep`, separate `data/prep` store.

## Deployer trace (token → first address)

```bash
python -m pump_prep deployers --limit 30 --max-age 365
# → pump_prep/out/deployer_trace.html
```

For each token: CoinGecko contract → Etherscan deployer → outbound transfers → match vs MM/fund seeds + CEX hot wallets.


| Type | Meaning |
|------|---------|
| new_token_in | Obscure / mid-cap ERC-20 inbound to seed |
| cex_deposit | Obscure token out from seed → known CEX hot wallet |
| shared_funder | Parent funded ≥3 EOAs with gas/stables |
| repeat_counterparty | Same address touches ≥2 seed entities |
