"""Alpaca paper adapter: paper host only, idempotent client order IDs."""

from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from lab.contracts.enums import OrderStatus, Side
from lab.execution.alpaca_paper import (
    ALLOWED_PAPER_HOSTS,
    LIVE_TRADING_HOST,
    AlpacaPaperBroker,
)
from tests.factories import make_order


class _FakeResponse:
    def __init__(self, payload: dict[str, object], status: int = 200) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _env() -> dict[str, str]:
    return {
        "ALPACA_API_KEY_ID": "paper-key",
        "ALPACA_API_SECRET_KEY": "paper-secret",
    }


def test_live_trading_host_is_refused() -> None:
    env = {
        **_env(),
        "ALPACA_PAPER_BASE_URL": f"https://{LIVE_TRADING_HOST}",
    }
    with pytest.raises(ValueError, match="live trading host"):
        AlpacaPaperBroker(env=env)


def test_http_paper_url_is_refused() -> None:
    env = {**_env(), "ALPACA_PAPER_BASE_URL": "http://paper-api.alpaca.markets"}
    with pytest.raises(ValueError, match="https"):
        AlpacaPaperBroker(env=env)


def test_unapproved_host_is_refused() -> None:
    env = {**_env(), "ALPACA_PAPER_BASE_URL": "https://example.com"}
    with pytest.raises(ValueError, match="unapproved"):
        AlpacaPaperBroker(env=env)


def test_submit_uses_client_order_id_and_does_not_echo_secrets() -> None:
    captured: list[Request] = []

    def opener(request: Request, timeout: float = 30) -> _FakeResponse:
        captured.append(request)
        url = request.get_full_url()
        if request.get_method() == "GET" and "by_client_order_id" in url:
            raise HTTPError(url, 404, "Not Found", hdrs=None, fp=BytesIO())
        return _FakeResponse(
            {
                "id": "broker-1",
                "client_order_id": make_order().client_order_id,
                "symbol": "SPY",
                "side": "buy",
                "qty": "10",
                "type": "market",
                "status": "accepted",
                "filled_qty": "0",
            }
        )

    broker = AlpacaPaperBroker(env=_env(), opener=opener)
    order = make_order()
    accepted = broker.submit_order(order)
    assert accepted.broker_order_id == "broker-1"
    assert accepted.client_order_id == order.client_order_id
    assert accepted.status is OrderStatus.ACCEPTED
    post = next(req for req in captured if req.get_method() == "POST")
    url = post.get_full_url()
    assert url.startswith("https://paper-api.alpaca.markets/")
    assert url.split("/")[2] in ALLOWED_PAPER_HOSTS
    assert _env()["ALPACA_API_SECRET_KEY"] not in url
    body = json.loads(post.data.decode("utf-8")) if post.data else {}
    assert body["client_order_id"] == order.client_order_id
    assert body["side"] == Side.BUY.value


def test_existing_client_order_id_is_returned_without_a_second_create() -> None:
    posts = 0

    def opener(request: Request, timeout: float = 30) -> _FakeResponse:
        nonlocal posts
        url = request.get_full_url()
        if request.get_method() == "GET" and "by_client_order_id" in url:
            return _FakeResponse(
                {
                    "id": "broker-existing",
                    "client_order_id": make_order().client_order_id,
                    "symbol": "SPY",
                    "side": "buy",
                    "qty": "10",
                    "type": "market",
                    "status": "filled",
                    "filled_qty": "10",
                    "filled_avg_price": "503.05",
                }
            )
        posts += 1
        raise AssertionError("must not POST when the client order id already exists")

    broker = AlpacaPaperBroker(env=_env(), opener=opener)
    order = make_order()
    first = broker.submit_order(order)
    second = broker.submit_order(order)
    assert first.broker_order_id == "broker-existing"
    assert second.broker_order_id == first.broker_order_id
    assert posts == 0
