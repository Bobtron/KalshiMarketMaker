import time
from concurrent.futures import TimeoutError
from typing import Dict

import requests

from ..factories import create_api
from ..logging_utils import build_logger
from ..selection.scoring import safe_float


def cancel_resting_orders_for_ticker(
    ticker: str,
    dynamic_config: Dict,
    logger,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
) -> bool:
    cleanup_logger = build_logger(f"Cleanup_{ticker}", dynamic_config.get("log_level", "INFO"))
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
                    except requests.exceptions.RequestException as request_exception:
                        cleanup_logger.error(f"Failed to cancel order {order_id} for {ticker}: {request_exception}")

                time.sleep(backoff_seconds)
            except requests.exceptions.RequestException as request_exception:
                cleanup_logger.error(f"Order cleanup request failed for {ticker}: {request_exception}")
                time.sleep(backoff_seconds)

        remaining = api.get_orders()
        if remaining:
            logger.error(f"Cleanup incomplete for {ticker}: {len(remaining)} resting orders still present")
            return False
        return True
    except requests.exceptions.RequestException as request_exception:
        logger.error(f"Final cleanup verification failed for {ticker}: {request_exception}")
        return False
    finally:
        api.logout()


def stop_worker_then_cancel(
    ticker: str,
    stop_event,
    future,
    dynamic_config: Dict,
    logger,
) -> bool:
    selector_cfg = dynamic_config.get("market_selector", {})
    shutdown_timeout_seconds = safe_float(
        selector_cfg.get("worker_shutdown_timeout_seconds", 15),
        15.0,
    )

    stop_event.set()
    try:
        future.result(timeout=shutdown_timeout_seconds)
    except TimeoutError:
        logger.error(f"Worker {ticker} did not stop within {shutdown_timeout_seconds:.1f}s; deferring cleanup")
        return False
    except Exception as worker_exception:
        logger.error(f"Worker {ticker} exited with error during shutdown: {worker_exception}")

    return cancel_resting_orders_for_ticker(ticker, dynamic_config, logger)
