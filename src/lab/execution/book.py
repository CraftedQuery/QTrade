"""Local paper book: cash plus long positions, mutated only by broker fills."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from lab.contracts import Fill
from lab.contracts.enums import FillSource, Side


class BookState:
    """Long-or-cash book used by the risk engine.

    Shadow fills must not call :meth:`apply_fill`. Only ``broker_paper`` fills
    change cash or positions, so the internal estimate cannot drift the book.
    """

    def __init__(
        self,
        cash: Decimal,
        *,
        starting_capital: Decimal,
        peak_equity: Decimal | None = None,
        session_start_equity: Decimal | None = None,
    ) -> None:
        if cash < 0:
            raise ValueError("cash cannot be negative")
        if starting_capital <= 0:
            raise ValueError("starting_capital must be positive")
        self.cash = cash
        self.starting_capital = starting_capital
        self.peak_equity = starting_capital if peak_equity is None else peak_equity
        self.session_start_equity = (
            starting_capital if session_start_equity is None else session_start_equity
        )
        self._qty: dict[str, Decimal] = {}
        self._avg: dict[str, Decimal] = {}

    @classmethod
    def empty(cls, starting_capital: Decimal) -> BookState:
        """A flat cash book at ``starting_capital``."""
        return cls(starting_capital, starting_capital=starting_capital)

    def quantity(self, symbol: str) -> Decimal:
        """Shares held in ``symbol``, or zero."""
        return self._qty.get(symbol, Decimal(0))

    def avg_price(self, symbol: str) -> Decimal | None:
        """Average entry price, if the name is held."""
        if self.quantity(symbol) <= 0:
            return None
        return self._avg[symbol]

    @property
    def held_symbols(self) -> tuple[str, ...]:
        """Names with a positive share count."""
        return tuple(sorted(symbol for symbol, qty in self._qty.items() if qty > 0))

    def marked_equity(self, prices: Mapping[str, Decimal]) -> Decimal:
        """Cash plus marked longs. Missing marks for a held name raise."""
        equity = self.cash
        for symbol, qty in self._qty.items():
            if qty <= 0:
                continue
            price = prices.get(symbol)
            if price is None:
                raise ValueError(f"missing mark price for {symbol}")
            equity += qty * price
        return equity

    def gross_exposure(self, prices: Mapping[str, Decimal]) -> Decimal:
        """Invested weight of current longs."""
        equity = self.marked_equity(prices)
        if equity <= 0:
            return Decimal(0)
        invested = Decimal(0)
        for symbol, qty in self._qty.items():
            if qty > 0:
                invested += qty * prices[symbol]
        return invested / equity

    def daily_loss_fraction(self, prices: Mapping[str, Decimal]) -> Decimal:
        """Loss since session start, or zero on a gain."""
        if self.session_start_equity <= 0:
            return Decimal(0)
        loss = self.session_start_equity - self.marked_equity(prices)
        if loss <= 0:
            return Decimal(0)
        return loss / self.session_start_equity

    def drawdown_fraction(self, prices: Mapping[str, Decimal]) -> Decimal:
        """Peak-to-trough fraction, marking the book and updating the peak."""
        equity = self.marked_equity(prices)
        if equity > self.peak_equity:
            self.peak_equity = equity
        if self.peak_equity <= 0:
            return Decimal(0)
        drawdown = self.peak_equity - equity
        if drawdown <= 0:
            return Decimal(0)
        return drawdown / self.peak_equity

    def start_session(self, prices: Mapping[str, Decimal]) -> None:
        """Reset the daily-loss baseline to the current mark."""
        equity = self.marked_equity(prices)
        self.session_start_equity = equity
        if equity > self.peak_equity:
            self.peak_equity = equity

    def apply_fill(self, fill: Fill) -> None:
        """Apply a broker paper fill. Shadow fills are rejected."""
        if fill.source is not FillSource.BROKER_PAPER:
            raise ValueError("shadow fills must not mutate the book")
        self.apply_broker_fill_quantity(
            fill.symbol,
            fill.quantity,
            fill.price,
            side_buy=fill.side is Side.BUY,
            fee=fill.fee,
        )

    def apply_broker_fill_quantity(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        *,
        side_buy: bool,
        fee: Decimal = Decimal(0),
    ) -> None:
        """Buy or sell ``quantity`` shares without going short."""
        if quantity <= 0:
            raise ValueError("fill quantity must be positive")
        if side_buy:
            notional = quantity * price + fee
            self.cash -= notional
            held = self.quantity(symbol)
            if held == 0:
                self._avg[symbol] = price
            else:
                self._avg[symbol] = ((held * self._avg[symbol]) + (quantity * price)) / (
                    held + quantity
                )
            self._qty[symbol] = held + quantity
            return
        held = self.quantity(symbol)
        if quantity > held:
            raise ValueError(f"sell of {quantity} {symbol} exceeds long {held}")
        self.cash += quantity * price - fee
        remaining = held - quantity
        if remaining == 0:
            self._qty.pop(symbol, None)
            self._avg.pop(symbol, None)
        else:
            self._qty[symbol] = remaining

    def local_positions(self) -> dict[str, Decimal]:
        """Positive share counts only."""
        return {symbol: qty for symbol, qty in self._qty.items() if qty > 0}


__all__ = ["BookState"]
