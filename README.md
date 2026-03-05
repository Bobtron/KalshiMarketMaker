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
      top_n: 8
      refresh_seconds: 20
      min_volume_24h: 100
      min_spread_cents: 1
      volume_weight: 0.5
      spread_weight: 0.5
      # series_ticker: "FED"
  market_maker:
    max_position: 5
    order_expiration: 28800
    gamma: 0.1
    k: 1.5
    sigma: 0.001
    T: 28800
    min_spread: 0.0
    position_limit_buffer: 0.1
    inventory_skew_factor: 0.001
  dt: 2.0
```

At each selector refresh, the runner scans open markets from Kalshi, ranks by weighted normalized volume/spread, and maintains workers for the current top-N tickers.

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
