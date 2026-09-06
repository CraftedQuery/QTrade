"""Optional Alpaca historical fetch: host allow-list, no keys required for fixtures."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from urllib.request import Request

import pytest

from lab.data.alpaca import ALLOWED_DATA_HOSTS, alpaca_keys_present, fetch_daily_bars


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_keys_absent_means_fixture_path_is_required() -> None:
    assert not alpaca_keys_present({})
    with pytest.raises(ValueError, match="committed offline run"):
        fetch_daily_bars(["SPY"], date(2022, 1, 1), date(2022, 1, 10), env={})


def test_live_trading_host_is_refused() -> None:
    env = {
        "ALPACA_API_KEY_ID": "paper-key",
        "ALPACA_API_SECRET_KEY": "paper-secret",
        "ALPACA_DATA_BASE_URL": "https://api.alpaca.markets",
    }
    with pytest.raises(ValueError, match="live trading host"):
        fetch_daily_bars(["SPY"], date(2022, 1, 1), date(2022, 1, 10), env=env)


def test_http_is_refused() -> None:
    env = {
        "ALPACA_API_KEY_ID": "paper-key",
        "ALPACA_API_SECRET_KEY": "paper-secret",
        "ALPACA_DATA_BASE_URL": "http://data.alpaca.markets",
    }
    with pytest.raises(ValueError, match="https"):
        fetch_daily_bars(["SPY"], date(2022, 1, 1), date(2022, 1, 10), env=env)


def test_fetch_parses_bars_and_does_not_echo_secrets() -> None:
    captured: list[Request] = []

    def opener(request: Request, timeout: float = 30) -> _FakeResponse:
        captured.append(request)
        return _FakeResponse(
            {
                "bars": {
                    "SPY": [
                        {
                            "t": "2022-08-01T04:00:00Z",
                            "o": 400.0,
                            "h": 405.0,
                            "l": 399.0,
                            "c": 403.0,
                            "v": 1000,
                            "vw": 402.5,
                            "n": 12,
                        }
                    ]
                },
                "next_page_token": None,
            }
        )

    env = {
        "ALPACA_API_KEY_ID": "paper-key",
        "ALPACA_API_SECRET_KEY": "paper-secret",
    }
    bars = fetch_daily_bars(
        ["SPY"],
        date(2022, 8, 1),
        date(2022, 8, 2),
        env=env,
        opener=opener,
        ingested_at=datetime(2026, 9, 6, tzinfo=UTC),
    )
    assert len(bars) == 1
    assert bars[0].symbol == "SPY"
    assert bars[0].source == "alpaca-iex"
    assert bars[0].information_time == bars[0].ts_end
    url = captured[0].get_full_url()
    assert url.startswith("https://data.alpaca.markets/")
    host = url.split("/")[2]
    assert host in ALLOWED_DATA_HOSTS
    assert env["ALPACA_API_SECRET_KEY"] not in url
