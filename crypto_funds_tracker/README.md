# Crypto Funds Portfolio Tracker

Таблица публичных DAT/компаний (CoinGecko) + цены/волатильность с бирж (ccxt) + опционально VC через Arkham.

## Запуск

```bash
cd crypto_funds_tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python demo.py    # синтетика, без ключей
python main.py    # живые данные (нужен интернет)
```

Отчёт: `out/crypto_funds_report.html`

## Фокус (твой кейс)

- Капа **$50M–$600M** (`MCAP_MIN_USD` / `MCAP_MAX_USD`)
- BTC/ETH выкинуты
- Без Arkham API **холдинги VC = н/д** — таблица = mid-cap рынок + vol/chg

## Что есть без ключей

| Блок | Источник | Данные |
|------|----------|--------|
| Mid-cap watch | CoinGecko `coins/markets` | токен, mcap, цена, % за периоды |
| Vol / Chg 3·6·9m | CoinGecko `market_chart` (top-N по объёму) | annualized vol %, % change |
| Цены CEX | ccxt top-20 по объёму | Binance/Bybit/OKX/BingX |
| Public / DAT | выкл. по умолчанию (`INCLUDE_DAT_TREASURIES=False`) | почти только BTC/ETH |

## Arkham (VC)

У тебя API нет → блок фондов недоступен. Пароль/логин не используем.  
Если появится API key — впиши в `config.py` → `ARKHAM_API_KEY`.

## UI отчёта

- Сортировка по клику на любую колонку
- Цвет токена одинаковый во всех строках + фильтр-чипы
- Поиск по фонду/токену
- «н/д» где официальных данных нет (`held_since` для DAT на free list, entry VC и т.п.)
