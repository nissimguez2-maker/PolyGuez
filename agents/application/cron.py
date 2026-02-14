from agents.application.trade import Trader

import time

from scheduler import Scheduler as BaseScheduler
from scheduler.trigger import Monday


class TradingScheduler:
    def __init__(self) -> None:
        self.trader = Trader()
        self.schedule = BaseScheduler()

    def start(self) -> None:
        while True:
            self.schedule.exec_jobs()
            time.sleep(1)


class TradingAgent(TradingScheduler):
    def __init__(self) -> None:
        super().__init__()
        self.trader = Trader()
        self.weekly(Monday(), self.trader.one_best_trade)
