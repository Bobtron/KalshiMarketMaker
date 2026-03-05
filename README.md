# Kalshi Market Making Algorithm

This project implements a market making algorithm for Kalshi markets. It now supports a simple dynamic mode with a two-step flow:
1) select top markets by volume + spread, and 2) run Avellaneda-Stoikov market making on those selected tickers.

## Local Setup

1. Clone the repository
2. Install dependencies:
   ```
   uv pip install -e .
   ```
3. Create a `.env` file with your Kalshi credentials:
   ```
   KALSHI_API_KEY_ID=your_api_key_id
   KALSHI_PRIVATE_KEY_PATH=/absolute/path/to/your/private-key.key
   KALSHI_BASE_URL=https://demo-api.kalshi.co/trade-api/v2
   ```
   Use `https://api.elections.kalshi.com/trade-api/v2` for production.
4. Create or modify `config.yaml`.
5. Run the script:
   ```
   kalshi-mm --config config.yaml
   ```

## Configuration

Use dynamic mode with one `dynamic` block:

```yaml
dynamic:
   log_level: INFO
  api:
    trade_side: "yes"
   market_selector:
      enabled: true
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

At each selector refresh, the runner scans open markets from Kalshi, ranks by weighted normalized volume/spread, and maintains workers for the current top-N tickers.
When a ticker is deselected, the runner enforces a cleanup sequence: stop worker, wait up to `worker_shutdown_timeout_seconds`, cancel resting orders for that ticker, and verify cleanup before removing it from active state.

## Cancel All Resting Orders

Use the operational command below to cancel resting orders across all markets.

```bash
kalshi-cancel-all
```

Optional flags:

- Preview only (no cancel):
   ```bash
   kalshi-cancel-all --dry-run
   ```
- Restrict to one market ticker:
   ```bash
   kalshi-cancel-all --ticker FEDDECISION-24NOV-H0
   ```
- Restrict by side or action:
   ```bash
   kalshi-cancel-all --side yes --action buy
   ```
- Limit cancellations:
   ```bash
   kalshi-cancel-all --max-cancels 10
   ```

## Deploying on fly.io

1. Install the flyctl CLI: https://fly.io/docs/hands-on/install-flyctl/
2. Login to fly.io:
   ```
   flyctl auth login
   ```
3. Navigate to your project directory and initialize your fly.io app:
   ```
   flyctl launch
   ```
   Follow the prompts, but don't deploy yet.
4. Set your Kalshi credentials and base URL as secrets:
   ```
   flyctl secrets set KALSHI_API_KEY_ID=your_api_key_id
   flyctl secrets set KALSHI_PRIVATE_KEY_PATH=/app/keys/kalshi-private.key
   flyctl secrets set KALSHI_BASE_URL=https://demo-api.kalshi.co/trade-api/v2
   ```
5. Ensure your `config.yaml` file is in the project directory and contains your `dynamic` settings.
6. Deploy the app:
   ```
   flyctl deploy
   ```

The deployment will use `runner.py`, which runs the selector loop and manages top-N market-maker workers.

## Monitoring

Runtime output is written to standard output (console), which can be monitored via fly.io logs:

```
flyctl logs
```

For more detailed instructions on monitoring and managing your deployment, refer to the fly.io documentation.
