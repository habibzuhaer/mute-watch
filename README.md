# MUTE — DWF Labs inbound activity → Telegram

Lightweight poller for **Termix Android**: the monitor runs on your server; you SSH in via Termix to start/stop/check; alerts arrive in Telegram.

## Quick start (ordered)

```bash
./START.sh                      # DWF monitor + HTML dashboard
# open http://127.0.0.1:8765/   # control panel: start/stop + reports
```

| Step | Action | Result |
|------|--------|--------|
| 1 | `./scripts/start_dashboard.sh` | HTML панель + API |
| 2 | **Старт системы** в панели | DWF + prep → Telegram |
| 3 | **Запустить сканы** | prep + deployer HTML |
| 4 | Блок **Отчёты** | таблицы в браузере |

## What it does

Watches known **DWF Labs–related wallets** and sends a Telegram message on **any inbound** native/token transfer (ERC-20 / SPL / TRC-20 / native).

First run **bootstraps** existing history as “seen” so you are not flooded with old transfers.

## Termix (Android) usage

1. SSH into this host in Termix.
2. `cd ~/MUTE`
3. Fill `.env` (see below).
4. Start:

```bash
chmod +x scripts/*.sh START.sh
./START.sh
./scripts/status.sh
./scripts/test_telegram.sh
```

Stop: `./scripts/stop.sh` (DWF) · `./scripts/stop.sh --all` (DWF+prep+dashboard)

Process uses `nohup` — survives Termix disconnect.

## Config

Copy `.env.example` → `.env`:

| Key | Need |
|-----|------|
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | required |
| `ETHERSCAN_API_KEY` | required for EVM (one key, many chains via V2) |
| `TRONGRID_API_KEY` | optional (higher Tron limits) |
| `HELIUS_API_KEY` | optional (better Solana RPC) |
| `CHAIN_PROFILE` | `core` / `wide` / `max` |
| `POLL_PRESET` | `5m` (default) or `15m` — latency not critical; history is enough |
| `PARALLEL` / `PARALLEL_WORKERS` | `1` / `6` — parallel wallets + EVM chains; global pace keeps API spacing |
| `ALERT_MODE` | `all` (classic) or `prep` (obscure IN + CEX OUT) |
| `ADDRESSES_FILE` | default `addresses/dwf_labs.json`; prep uses `pump_prep_watchlist.json` |

Addresses: `addresses/dwf_labs.json` — add any new related wallets there.

## Pump prep (early signals + graph)

```bash
python -m pump_prep run
python -m pump_prep deployers --limit 40 --max-age 365
./scripts/start_prep.sh
```

See `pump_prep/README.md`. Reports: `pump_prep/out/*.html`.

## Resource cost (honest)

Do **not** run the poller on the phone. Termix only controls the server.

Latency model: **fact of inbound transfer**, not realtime. Each cycle reads recent history (up to ~100 txs/address/chain) and dedups — so 5–15 min gaps are fine.

| Profile | EVM chains | ~API calls / cycle | @ 5m | @ 15m |
|---------|------------|--------------------|------|-------|
| `core`  | 4          | ~45–50             | ~600/h | ~200/h |
| `wide`  | 12         | ~124               | ~1.5k/h | ~500/h |
| `max`   | ~18        | ~200+              | heavier | still OK on free tier often |

Also:

- **RAM**: ~30–60 MB  
- **CPU**: idle between polls  
- **Free Etherscan**: much safer at 5m/15m than sub-minute polling  
- **“All networks” literally** needs paid indexers; this covers chains where DWF moves size  

```bash
python -m mute estimate
```

## Commands

```bash
./scripts/start_dashboard.sh
./scripts/start.sh
./scripts/start_prep.sh
./scripts/status.sh
./scripts/stop.sh --all
python -m mute estimate
python -m mute wallets
python -m mute test-telegram
python -m mute once
python -m mute run
python -m pump_prep run
python -m pump_prep deployers
```

## Addresses included

- Official secondary-market: EVM / TRON / SOL (Grachev disclosure May 2025)  
- Public Arkham/Etherscan-labeled DWF wallets and closely linked cluster addresses  

DWF uses many opaque MM wallets; labels lag. Append new addresses to `addresses/dwf_labs.json` when you find them.
