# Kalshi Market Maker

Dynamic market-making bot for Kalshi with explicit safety controls and operational tooling.

## Algorithm

The runtime is a two-step loop:

1. Market selection
   - Pull open markets from Kalshi.
   - Filter using `min_volume_24h` and `min_spread_cents`.
   - Score candidates with weighted normalized volume and spread.
   - Keep the top `top_n` markets.

2. Market making
   - Run one Avellaneda-Stoikov worker per selected market.
   - Each worker computes reservation price, asymmetric quotes, and order sizes.
   - Worker manages resting orders on each loop interval.

## Lifecycle and Safety

- Dynamic-only runtime: this project runs from `dynamic` config.
- Deselect cleanup invariant:
  - stop worker,
  - wait up to `worker_shutdown_timeout_seconds`,
  - cancel all resting orders for that ticker,
  - verify cleanup before removing worker state.
- Selector and API requests use retry/backoff handling for transient and rate-limit errors.

## Local Setup

1. Install dependencies

   ```bash
   uv pip install -e .
   ```

2. Set environment variables in `.env`

   ```bash
   KALSHI_API_KEY_ID=your_api_key_id
   KALSHI_PRIVATE_KEY_PATH=/absolute/path/to/your/private-key.key
   KALSHI_BASE_URL=https://demo-api.kalshi.co/trade-api/v2
   ```

   Use `https://api.elections.kalshi.com/trade-api/v2` for production.

3. Run bot

   ```bash
   kalshi-mm --config config.yaml
   ```

## Configuration

```yaml
dynamic:
  log_level: INFO
  market_selector:
    top_n: 3
    refresh_seconds: 45
    worker_shutdown_timeout_seconds: 15
    min_volume_24h: 500
    min_spread_cents: 2
    volume_weight: 0.35
    spread_weight: 0.65
    page_limit: 250
    max_pages: 5
    max_markets: 1250
    # series_ticker: "FED"
  market_maker:
    max_position: 3
    order_expiration: 3600
    gamma: 0.2
    k: 1.5
    sigma: 0.001
    T: 28800
    min_spread: 0.02
    position_limit_buffer: 0.05
    inventory_skew_factor: 0.001
    trade_side: "yes"
  dt: 5.0
```

## Operations

Cancel resting orders across all markets:

```bash
kalshi-cancel-all
```

Dry-run preview:

```bash
kalshi-cancel-all --dry-run
```

Scoped cancellation examples:

```bash
kalshi-cancel-all --ticker FEDDECISION-24NOV-H0
kalshi-cancel-all --side yes --action buy
kalshi-cancel-all --max-cancels 10
```

Liquidate entire book (cancel resting orders first, then submit flattening orders):

```bash
kalshi-cancel-all --liquidate-all
```

Dry-run liquidation preview:

```bash
kalshi-cancel-all --liquidate-all --dry-run
```

Liquidation controls:

```bash
kalshi-cancel-all --liquidate-all --max-liquidations 25 --liquidation-expiration-seconds 120
```

Note: liquidation currently uses signed-yes position convention:
- `position > 0` -> `sell yes` at current `yes_bid`
- `position < 0` -> `buy yes` at current `yes_ask`

## Deployment

Deploy with Fly:

```bash
flyctl deploy
```

Set secrets:

```bash
flyctl secrets set KALSHI_API_KEY_ID=your_api_key_id
flyctl secrets set KALSHI_PRIVATE_KEY_PATH=/app/keys/kalshi-private.key
flyctl secrets set KALSHI_BASE_URL=https://demo-api.kalshi.co/trade-api/v2
```

## Monitoring

Logs are written to stdout.

```bash
flyctl logs
```
