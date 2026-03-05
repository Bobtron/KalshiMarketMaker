import argparse
import logging
import os
from typing import Dict, List

from dotenv import load_dotenv

from runner import create_api


def _build_logger(level: str) -> logging.Logger:
    logger = logging.getLogger("CancelAllOrders")
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def _filter_orders(orders: List[Dict], side: str = None, action: str = None) -> List[Dict]:
    filtered = orders

    if side:
        filtered = [order for order in filtered if order.get("side") == side]

    if action:
        filtered = [order for order in filtered if order.get("action") == action]

    return filtered


def main():
    parser = argparse.ArgumentParser(
        description="Cancel resting Kalshi orders (all tickers by default)."
    )
    parser.add_argument("--ticker", type=str, default=None, help="Optional market ticker filter")
    parser.add_argument("--side", type=str, choices=["yes", "no"], default=None, help="Optional side filter")
    parser.add_argument("--action", type=str, choices=["buy", "sell"], default=None, help="Optional action filter")
    parser.add_argument("--max-cancels", type=int, default=None, help="Optional max number of orders to cancel")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview matching resting orders without canceling",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    args = parser.parse_args()

    load_dotenv()
    logger = _build_logger(args.log_level)

    api = create_api({}, logger, market_ticker="DYNAMIC")

    try:
        resting_orders = api.list_all_resting_orders(ticker=args.ticker)
        filtered_orders = _filter_orders(resting_orders, side=args.side, action=args.action)

        if args.max_cancels is not None and args.max_cancels >= 0:
            filtered_orders = filtered_orders[: args.max_cancels]

        logger.info(
            f"Matched {len(filtered_orders)} resting orders "
            f"(from {len(resting_orders)} total resting orders)."
        )

        if not filtered_orders:
            logger.info("No matching resting orders found. Nothing to do.")
            return

        for order in filtered_orders:
            ticker = order.get("ticker", "UNKNOWN")
            order_id = order.get("order_id")
            side = order.get("side", "unknown")
            action = order.get("action", "unknown")
            logger.info(f"Order {order_id} | ticker={ticker} | side={side} | action={action}")

        if args.dry_run:
            logger.warning("Dry-run enabled: no orders were canceled")
            return

        canceled = 0
        failed = 0

        for order in filtered_orders:
            order_id = order.get("order_id")
            if order_id is None:
                failed += 1
                logger.error("Skipping order without order_id")
                continue

            try:
                success = api.cancel_order(order_id)
                if success:
                    canceled += 1
                else:
                    failed += 1
                    logger.error(f"Cancel returned no reduction for order {order_id}")
            except Exception as exc:
                failed += 1
                logger.error(f"Failed to cancel order {order_id}: {exc}")

        logger.info(
            f"Cancellation complete. canceled={canceled}, failed={failed}, total_attempted={len(filtered_orders)}"
        )
    finally:
        api.logout()


if __name__ == "__main__":
    main()
