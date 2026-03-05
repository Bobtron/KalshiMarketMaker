import argparse
import time
from typing import Dict, List

from dotenv import load_dotenv

from ..factories import create_api
from ..logging_utils import build_logger


def filter_orders(orders: List[Dict], side: str = None, action: str = None) -> List[Dict]:
    filtered = orders
    if side:
        filtered = [order for order in filtered if order.get("side") == side]
    if action:
        filtered = [order for order in filtered if order.get("action") == action]
    return filtered


def parse_position(raw_position) -> int:
    try:
        return int(float(raw_position))
    except (TypeError, ValueError):
        return 0


def main():
    parser = argparse.ArgumentParser(description="Cancel resting Kalshi orders (all tickers by default)")
    parser.add_argument("--ticker", type=str, default=None, help="Optional market ticker filter")
    parser.add_argument("--side", type=str, choices=["yes", "no"], default=None, help="Optional side filter")
    parser.add_argument("--action", type=str, choices=["buy", "sell"], default=None, help="Optional action filter")
    parser.add_argument("--max-cancels", type=int, default=None, help="Optional max number of orders to cancel")
    parser.add_argument(
        "--liquidate-all",
        action="store_true",
        help="After canceling resting orders, submit flattening orders for all non-zero positions",
    )
    parser.add_argument(
        "--max-liquidations",
        type=int,
        default=None,
        help="Optional max number of position liquidation orders",
    )
    parser.add_argument(
        "--liquidation-expiration-seconds",
        type=int,
        default=120,
        help="Expiration horizon for liquidation orders",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview matching orders without canceling")
    parser.add_argument("--log-level", type=str, default="INFO", help="Logging level")
    args = parser.parse_args()

    load_dotenv()
    logger = build_logger("CancelAllOrders", args.log_level)
    api = create_api({}, logger, market_ticker="DYNAMIC")

    try:
        resting_orders = api.list_all_resting_orders(ticker=args.ticker)
        filtered_orders = filter_orders(resting_orders, side=args.side, action=args.action)

        if args.max_cancels is not None and args.max_cancels >= 0:
            filtered_orders = filtered_orders[: args.max_cancels]

        logger.info(
            f"Matched {len(filtered_orders)} resting orders (from {len(resting_orders)} total resting orders)."
        )

        if filtered_orders:
            for order in filtered_orders:
                logger.info(
                    f"Order {order.get('order_id')} | ticker={order.get('ticker', 'UNKNOWN')} "
                    f"| side={order.get('side', 'unknown')} | action={order.get('action', 'unknown')}"
                )
        else:
            logger.info("No matching resting orders found.")

        if args.dry_run:
            logger.warning("Dry-run enabled: no order cancellations executed")
        else:
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
                except Exception as cancel_exception:
                    failed += 1
                    logger.error(f"Failed to cancel order {order_id}: {cancel_exception}")

            logger.info(
                f"Cancellation complete. canceled={canceled}, failed={failed}, total_attempted={len(filtered_orders)}"
            )

        if not args.liquidate_all:
            return

        positions = api.list_all_positions()
        liquidation_candidates = []

        for position in positions:
            ticker = position.get("ticker")
            if not ticker:
                continue
            if args.ticker and ticker != args.ticker:
                continue

            signed_position = parse_position(position.get("position", 0))
            if signed_position == 0:
                continue

            market = api.get_market(ticker)
            market_data = market.get("market", {})

            if signed_position > 0:
                action = "sell"
                side = "yes"
                price_cents = market_data.get("yes_bid")
                quantity = signed_position
            else:
                action = "buy"
                side = "yes"
                price_cents = market_data.get("yes_ask")
                quantity = abs(signed_position)

            if price_cents is None:
                logger.error(f"Skipping liquidation for {ticker}: missing market quote")
                continue

            liquidation_candidates.append(
                {
                    "ticker": ticker,
                    "action": action,
                    "side": side,
                    "price": float(price_cents) / 100,
                    "quantity": quantity,
                    "signed_position": signed_position,
                }
            )

        if args.max_liquidations is not None and args.max_liquidations >= 0:
            liquidation_candidates = liquidation_candidates[: args.max_liquidations]

        logger.warning(
            f"Liquidation mode selected. Candidates={len(liquidation_candidates)} (signed-yes position convention)."
        )

        for candidate in liquidation_candidates:
            logger.warning(
                f"Liquidate ticker={candidate['ticker']} pos={candidate['signed_position']} "
                f"via {candidate['action']} {candidate['side']} qty={candidate['quantity']} @ {candidate['price']:.2f}"
            )

        if not liquidation_candidates:
            logger.info("No non-zero positions found for liquidation")
            return

        if args.dry_run:
            logger.warning("Dry-run enabled: no liquidation orders executed")
            return

        liquidation_success = 0
        liquidation_failed = 0
        expiration_ts = int(time.time()) + max(1, args.liquidation_expiration_seconds)

        for candidate in liquidation_candidates:
            try:
                order_id = api.place_order_for_ticker(
                    ticker=candidate["ticker"],
                    action=candidate["action"],
                    side=candidate["side"],
                    price=candidate["price"],
                    quantity=candidate["quantity"],
                    expiration_ts=expiration_ts,
                )
                liquidation_success += 1
                logger.warning(f"Submitted liquidation order {order_id} for {candidate['ticker']}")
            except Exception as liquidation_exception:
                liquidation_failed += 1
                logger.error(
                    f"Failed liquidation for {candidate['ticker']}: {liquidation_exception}"
                )

        logger.warning(
            f"Liquidation complete. submitted={liquidation_success}, failed={liquidation_failed}, "
            f"total_attempted={len(liquidation_candidates)}"
        )
    finally:
        api.logout()


if __name__ == "__main__":
    main()
