import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import yaml
from dotenv import load_dotenv
import os
from typing import Dict, List, Tuple
import threading
import time
import requests

from mm import KalshiTradingAPI, AvellanedaMarketMaker

def load_config(config_file):
    with open(config_file, 'r') as f:
        return yaml.safe_load(f)

def create_api(api_config, logger, market_ticker: str = None):
    ticker = market_ticker if market_ticker is not None else api_config.get('market_ticker', 'DYNAMIC')
    return KalshiTradingAPI(
        api_key_id=os.getenv("KALSHI_API_KEY_ID"),
        private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH"),
        market_ticker=ticker,
        base_url=os.getenv("KALSHI_BASE_URL"),
        logger=logger,
    )

def create_market_maker(mm_config, api, logger):
    return AvellanedaMarketMaker(
        logger=logger,
        api=api,
        gamma=mm_config.get('gamma', 0.1),
        k=mm_config.get('k', 1.5),
        sigma=mm_config.get('sigma', 0.5),
        T=mm_config.get('T', 3600),
        max_position=mm_config.get('max_position', 100),
        order_expiration=mm_config.get('order_expiration', 300),
        min_spread=mm_config.get('min_spread', 0.01),
        position_limit_buffer=mm_config.get('position_limit_buffer', 0.1),
        inventory_skew_factor=mm_config.get('inventory_skew_factor', 0.01),
        trade_side=mm_config.get('trade_side', 'yes')
    )

def run_strategy(config_name: str, config: Dict):
    logger = logging.getLogger(f"Strategy_{config_name}")
    logger.setLevel(config.get('log_level', 'INFO'))

    if not logger.handlers:
        ch = logging.StreamHandler()
        ch.setLevel(config.get('log_level', 'INFO'))
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    logger.info(f"Starting strategy: {config_name}")

    # Create API
    api = create_api(config['api'], logger)

    # Create market maker
    market_maker = create_market_maker(config['market_maker'], api, logger)

    try:
        # Run market maker
        market_maker.run(config.get('dt', 1.0))
    except KeyboardInterrupt:
        logger.info("Market maker stopped by user")
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
    finally:
        # Ensure logout happens even if an exception occurs
        api.logout()

def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def _compute_spread_cents(market: Dict) -> float:
    yes_bid = _safe_float(market.get("yes_bid"), -1)
    yes_ask = _safe_float(market.get("yes_ask"), -1)
    if yes_bid < 0 or yes_ask < 0:
        return -1
    return yes_ask - yes_bid

def select_top_markets(markets: List[Dict], selector_cfg: Dict) -> List[Tuple[str, float, float, float]]:
    min_volume_24h = _safe_float(selector_cfg.get("min_volume_24h", 100))
    min_spread_cents = _safe_float(selector_cfg.get("min_spread_cents", 1))
    top_n = int(selector_cfg.get("top_n", 8))
    volume_weight = _safe_float(selector_cfg.get("volume_weight", 0.5))
    spread_weight = _safe_float(selector_cfg.get("spread_weight", 0.5))

    candidates = []
    for market in markets:
        ticker = market.get("ticker")
        if not ticker:
            continue

        volume_24h = _safe_float(market.get("volume_24h", market.get("volume", 0)))
        spread_cents = _compute_spread_cents(market)

        if volume_24h < min_volume_24h:
            continue
        if spread_cents < min_spread_cents:
            continue

        candidates.append(
            {
                "ticker": ticker,
                "volume_24h": volume_24h,
                "spread_cents": spread_cents,
            }
        )

    if not candidates:
        return []

    volumes = [m["volume_24h"] for m in candidates]
    spreads = [m["spread_cents"] for m in candidates]

    min_v, max_v = min(volumes), max(volumes)
    min_s, max_s = min(spreads), max(spreads)

    def normalize(value: float, min_value: float, max_value: float) -> float:
        if max_value == min_value:
            return 1.0
        return (value - min_value) / (max_value - min_value)

    ranked = []
    for market in candidates:
        volume_norm = normalize(market["volume_24h"], min_v, max_v)
        spread_norm = normalize(market["spread_cents"], min_s, max_s)
        score = volume_weight * volume_norm + spread_weight * spread_norm
        ranked.append((market["ticker"], score, market["volume_24h"], market["spread_cents"]))

    ranked.sort(key=lambda row: row[1], reverse=True)
    return ranked[:top_n]

def run_market_worker(ticker: str, dynamic_config: Dict, stop_event: threading.Event):
    logger = logging.getLogger(f"Worker_{ticker}")
    log_level = dynamic_config.get('log_level', 'INFO')
    logger.setLevel(log_level)
    if not logger.handlers:
        ch = logging.StreamHandler()
        ch.setLevel(log_level)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    api = create_api(dynamic_config.get("api", {}), logger, market_ticker=ticker)
    mm_config = dynamic_config.get("market_maker", {})
    market_maker = create_market_maker(mm_config, api, logger)
    dt = dynamic_config.get("dt", 2.0)

    try:
        logger.info(f"Starting market maker worker for {ticker}")
        market_maker.run(dt, stop_event=stop_event)
    except Exception as exc:
        logger.error(f"Worker failed for {ticker}: {exc}")
    finally:
        api.logout()

def _cancel_resting_orders_for_ticker(
    ticker: str,
    dynamic_config: Dict,
    logger: logging.Logger,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
) -> bool:
    cleanup_logger = logging.getLogger(f"Cleanup_{ticker}")
    cleanup_logger.setLevel(dynamic_config.get('log_level', 'INFO'))
    if not cleanup_logger.handlers:
        ch = logging.StreamHandler()
        ch.setLevel(dynamic_config.get('log_level', 'INFO'))
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        cleanup_logger.addHandler(ch)

    api = create_api(dynamic_config.get("api", {}), cleanup_logger, market_ticker=ticker)
    try:
        for attempt in range(1, max_attempts + 1):
            try:
                orders = api.get_orders()
                if not orders:
                    cleanup_logger.info(f"No resting orders to cancel for {ticker}")
                    return True

                cleanup_logger.warning(
                    f"Found {len(orders)} resting orders for {ticker}. Cancel attempt {attempt}/{max_attempts}"
                )

                for order in orders:
                    order_id = order.get("order_id")
                    if order_id is None:
                        continue
                    try:
                        api.cancel_order(order_id)
                    except requests.exceptions.RequestException as exc:
                        cleanup_logger.error(f"Failed to cancel order {order_id} for {ticker}: {exc}")

                time.sleep(backoff_seconds)
            except requests.exceptions.RequestException as exc:
                cleanup_logger.error(f"Order cleanup request failed for {ticker}: {exc}")
                time.sleep(backoff_seconds)

        remaining = api.get_orders()
        if remaining:
            logger.error(f"Cleanup incomplete for {ticker}: {len(remaining)} resting orders still present")
            return False
        return True
    except requests.exceptions.RequestException as exc:
        logger.error(f"Final cleanup verification failed for {ticker}: {exc}")
        return False
    finally:
        api.logout()

def _stop_worker_then_cancel(
    ticker: str,
    stop_event: threading.Event,
    future,
    dynamic_config: Dict,
    logger: logging.Logger,
) -> bool:
    selector_cfg = dynamic_config.get("market_selector", {})
    shutdown_timeout_seconds = _safe_float(
        selector_cfg.get("worker_shutdown_timeout_seconds", 15),
        15.0,
    )

    stop_event.set()
    try:
        future.result(timeout=shutdown_timeout_seconds)
    except TimeoutError:
        logger.error(
            f"Worker {ticker} did not stop within {shutdown_timeout_seconds:.1f}s; deferring cleanup"
        )
        return False
    except Exception as exc:
        logger.error(f"Worker {ticker} exited with error during shutdown: {exc}")

    return _cancel_resting_orders_for_ticker(ticker, dynamic_config, logger)

def run_dynamic_strategy(dynamic_config: Dict):
    logger = logging.getLogger("DynamicSelector")
    log_level = dynamic_config.get('log_level', 'INFO')
    logger.setLevel(log_level)
    if not logger.handlers:
        ch = logging.StreamHandler()
        ch.setLevel(log_level)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    selector_cfg = dynamic_config.get("market_selector", {})
    refresh_seconds = _safe_float(selector_cfg.get("refresh_seconds", 20), 20.0)
    series_ticker = selector_cfg.get("series_ticker")
    page_limit = int(selector_cfg.get("page_limit", 250))
    max_pages = int(selector_cfg.get("max_pages", 5))
    max_markets = int(selector_cfg.get("max_markets", 1250))

    selector_api = create_api(dynamic_config.get("api", {}), logger, market_ticker="DYNAMIC")
    active_workers: Dict[str, Tuple[threading.Event, object]] = {}
    max_workers = int(selector_cfg.get("top_n", 8)) + 1
    last_selected_tickers: List[str] = []
    selector_backoff_seconds = 5.0
    max_selector_backoff_seconds = 120.0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        try:
            while True:
                markets: List[Dict] = []
                selected_tickers = last_selected_tickers

                try:
                    markets = selector_api.list_all_open_markets(
                        series_ticker=series_ticker,
                        page_limit=page_limit,
                        max_pages=max_pages,
                        max_markets=max_markets,
                    )
                    ranked = select_top_markets(markets, selector_cfg)
                    selected_tickers = [ticker for ticker, _, _, _ in ranked]
                    last_selected_tickers = selected_tickers
                    selector_backoff_seconds = 5.0
                except requests.exceptions.HTTPError as exc:
                    status_code = exc.response.status_code if exc.response is not None else None
                    if status_code == 429:
                        logger.warning(
                            f"Selector rate-limited (429). Reusing previous selection for now and backing off for "
                            f"{selector_backoff_seconds:.1f}s"
                        )
                        time.sleep(selector_backoff_seconds)
                        selector_backoff_seconds = min(
                            selector_backoff_seconds * 2,
                            max_selector_backoff_seconds,
                        )
                    else:
                        logger.error(f"Selector HTTP error ({status_code}): {exc}")
                        time.sleep(selector_backoff_seconds)
                except requests.exceptions.RequestException as exc:
                    logger.error(f"Selector request error: {exc}")
                    time.sleep(selector_backoff_seconds)

                selected_set = set(selected_tickers)

                logger.info(f"Selector found {len(markets)} open markets; selected: {selected_tickers}")

                for ticker in list(active_workers.keys()):
                    stop_event, future = active_workers[ticker]
                    if ticker not in selected_set:
                        logger.warning(f"Draining deselected ticker {ticker}: stop worker then cancel resting orders")
                        is_clean = _stop_worker_then_cancel(
                            ticker,
                            stop_event,
                            future,
                            dynamic_config,
                            logger,
                        )
                        if is_clean:
                            del active_workers[ticker]
                        else:
                            logger.error(
                                f"Could not fully clean up {ticker}; keeping worker state for next retry cycle"
                            )

                for ticker in selected_tickers:
                    if ticker not in active_workers:
                        logger.info(f"Starting worker for selected ticker {ticker}")
                        stop_event = threading.Event()
                        future = executor.submit(run_market_worker, ticker, dynamic_config, stop_event)
                        active_workers[ticker] = (stop_event, future)

                time.sleep(refresh_seconds)
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, shutting down dynamic strategy")
        finally:
            for ticker in list(active_workers.keys()):
                stop_event, future = active_workers[ticker]
                logger.warning(f"Final shutdown cleanup for {ticker}")
                _stop_worker_then_cancel(ticker, stop_event, future, dynamic_config, logger)
            selector_api.logout()

def main():
    parser = argparse.ArgumentParser(description="Kalshi Market Making Algorithm")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config file")
    args = parser.parse_args()

    # Load all configurations
    configs = load_config(args.config)

    # Load environment variables
    load_dotenv()

    if isinstance(configs, dict) and "dynamic" in configs:
        print("Starting dynamic strategy mode")
        run_dynamic_strategy(configs["dynamic"])
        return

    print("Starting the following strategies:")
    for config_name in configs:
        print(f"- {config_name}")

    with ThreadPoolExecutor(max_workers=len(configs)) as executor:
        for config_name, config in configs.items():
            executor.submit(run_strategy, config_name, config)


if __name__ == "__main__":
    main()