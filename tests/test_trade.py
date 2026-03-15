import importlib
import sys
import types
import unittest
from unittest import mock


def load_trade_module():
    sys.modules.pop("agents.application.trade", None)

    executor_module = types.ModuleType("agents.application.executor")
    gamma_module = types.ModuleType("agents.polymarket.gamma")
    polymarket_module = types.ModuleType("agents.polymarket.polymarket")

    class Executor:
        pass

    class GammaMarketClient:
        pass

    class Polymarket:
        pass

    executor_module.Executor = Executor
    gamma_module.GammaMarketClient = GammaMarketClient
    polymarket_module.Polymarket = Polymarket

    with mock.patch.dict(
        sys.modules,
        {
            "agents.application.executor": executor_module,
            "agents.polymarket.gamma": gamma_module,
            "agents.polymarket.polymarket": polymarket_module,
        },
    ):
        return importlib.import_module("agents.application.trade")


class TraderRetryTests(unittest.TestCase):
    def test_one_best_trade_raises_original_error_after_bounded_retries(self):
        trade_module = load_trade_module()
        trader = trade_module.Trader.__new__(trade_module.Trader)

        attempts = {"count": 0}

        def always_fail():
            attempts["count"] += 1
            raise RuntimeError("boom")

        trader.pre_trade_logic = always_fail

        with mock.patch("builtins.print"):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                trader.one_best_trade(max_retries=2)

        self.assertEqual(attempts["count"], 3)


if __name__ == "__main__":
    unittest.main()
