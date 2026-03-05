import math
import time
from typing import Dict, List, Tuple

from .interfaces import AbstractTradingAPI


class AvellanedaMarketMaker:
    def __init__(
        self,
        logger,
        api: AbstractTradingAPI,
        gamma: float,
        k: float,
        sigma: float,
        T: float,
        max_position: int,
        order_expiration: int,
        min_spread: float = 0.01,
        position_limit_buffer: float = 0.1,
        inventory_skew_factor: float = 0.01,
        trade_side: str = "yes",
    ):
        self.api = api
        self.logger = logger
        self.base_gamma = gamma
        self.k = k
        self.sigma = sigma
        self.T = T
        self.max_position = max_position
        self.order_expiration = order_expiration
        self.min_spread = min_spread
        self.position_limit_buffer = position_limit_buffer
        self.inventory_skew_factor = inventory_skew_factor
        self.trade_side = trade_side

    def run(self, dt: float, stop_event=None):
        start_time = time.time()
        while time.time() - start_time < self.T:
            if stop_event is not None and stop_event.is_set():
                self.logger.info("Stop signal received, shutting down market maker loop")
                break

            current_time = time.time() - start_time
            mid_prices = self.api.get_price()
            mid_price = mid_prices[self.trade_side]
            inventory = self.api.get_position()

            reservation_price = self.calculate_reservation_price(mid_price, inventory, current_time)
            bid_price, ask_price = self.calculate_asymmetric_quotes(mid_price, inventory, current_time)
            buy_size, sell_size = self.calculate_order_sizes(inventory)

            self.logger.info(
                f"t={current_time:.2f}s mid={mid_price:.4f} inventory={inventory} "
                f"reservation={reservation_price:.4f} bid={bid_price:.4f} ask={ask_price:.4f}"
            )

            self.manage_orders(bid_price, ask_price, buy_size, sell_size)
            time.sleep(dt)

        self.logger.info("Avellaneda market maker finished running")

    def calculate_asymmetric_quotes(self, mid_price: float, inventory: int, elapsed_time: float) -> Tuple[float, float]:
        reservation_price = self.calculate_reservation_price(mid_price, inventory, elapsed_time)
        base_spread = self.calculate_optimal_spread(elapsed_time, inventory)

        position_ratio = inventory / self.max_position
        spread_adjustment = base_spread * abs(position_ratio) * 3

        if inventory > 0:
            bid_spread = base_spread / 2 + spread_adjustment
            ask_spread = max(base_spread / 2 - spread_adjustment, self.min_spread / 2)
        else:
            bid_spread = max(base_spread / 2 - spread_adjustment, self.min_spread / 2)
            ask_spread = base_spread / 2 + spread_adjustment

        bid_price = max(0, min(mid_price, reservation_price - bid_spread))
        ask_price = min(1, max(mid_price, reservation_price + ask_spread))

        return bid_price, ask_price

    def calculate_reservation_price(self, mid_price: float, inventory: int, elapsed_time: float) -> float:
        dynamic_gamma = self.calculate_dynamic_gamma(inventory)
        inventory_skew = inventory * self.inventory_skew_factor * mid_price
        return mid_price + inventory_skew - inventory * dynamic_gamma * (self.sigma ** 2) * (1 - elapsed_time / self.T)

    def calculate_optimal_spread(self, elapsed_time: float, inventory: int) -> float:
        dynamic_gamma = self.calculate_dynamic_gamma(inventory)
        base_spread = (
            dynamic_gamma * (self.sigma ** 2) * (1 - elapsed_time / self.T)
            + (2 / dynamic_gamma) * math.log(1 + (dynamic_gamma / self.k))
        )
        position_ratio = abs(inventory) / self.max_position
        spread_adjustment = 1 - (position_ratio ** 2)
        return max(base_spread * spread_adjustment * 0.01, self.min_spread)

    def calculate_dynamic_gamma(self, inventory: int) -> float:
        position_ratio = inventory / self.max_position
        return self.base_gamma * math.exp(-abs(position_ratio))

    def calculate_order_sizes(self, inventory: int) -> Tuple[int, int]:
        remaining_capacity = self.max_position - abs(inventory)
        buffer_size = int(self.max_position * self.position_limit_buffer)

        if inventory > 0:
            buy_size = max(1, min(buffer_size, remaining_capacity))
            sell_size = max(1, self.max_position)
        else:
            buy_size = max(1, self.max_position)
            sell_size = max(1, min(buffer_size, remaining_capacity))

        return buy_size, sell_size

    def manage_orders(self, bid_price: float, ask_price: float, buy_size: int, sell_size: int):
        current_orders = self.api.get_orders()

        buy_orders: List[Dict] = []
        sell_orders: List[Dict] = []

        for order in current_orders:
            if order["side"] == self.trade_side:
                if order["action"] == "buy":
                    buy_orders.append(order)
                elif order["action"] == "sell":
                    sell_orders.append(order)

        self.handle_order_side("buy", buy_orders, bid_price, buy_size)
        self.handle_order_side("sell", sell_orders, ask_price, sell_size)

    def handle_order_side(self, action: str, orders: List[Dict], desired_price: float, desired_size: int):
        keep_order = None

        for order in orders:
            current_price = (
                float(order["yes_price"]) / 100
                if self.trade_side == "yes"
                else float(order["no_price"]) / 100
            )
            if (
                keep_order is None
                and abs(current_price - desired_price) < 0.01
                and order["remaining_count"] == desired_size
            ):
                keep_order = order
            else:
                self.api.cancel_order(order["order_id"])

        current_price = self.api.get_price()[self.trade_side]
        should_place = (action == "buy" and desired_price < current_price) or (
            action == "sell" and desired_price > current_price
        )

        if keep_order is None and should_place:
            self.api.place_order(
                action,
                self.trade_side,
                desired_price,
                desired_size,
                int(time.time()) + self.order_expiration,
            )
