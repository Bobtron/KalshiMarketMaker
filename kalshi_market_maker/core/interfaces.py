import abc
from typing import Dict, List


class AbstractTradingAPI(abc.ABC):
    @abc.abstractmethod
    def get_price(self) -> Dict[str, float]:
        raise NotImplementedError

    @abc.abstractmethod
    def place_order(self, action: str, side: str, price: float, quantity: int, expiration_ts: int = None) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def get_position(self) -> int:
        raise NotImplementedError

    @abc.abstractmethod
    def get_orders(self) -> List[Dict]:
        raise NotImplementedError
