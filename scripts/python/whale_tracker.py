"""
Whale Tracker — Monitor top Polymarket traders and generate copy-trade signals.

Architecture:
  - Polls Polymarket Data API for whale wallet positions every 60s
  - Detects new positions, size changes, and exits
  - Generates signals when multiple whales bet same direction
  - Integrates with AutoTrader as strategy input

Usage:
    tracker = WhaleTracker()
    await tracker.start()
    signals = tracker.get_signals()
    await tracker.stop()
"""

import asyncio
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Top Polymarket traders to monitor (wallet addresses)
# These are publicly known profitable wallets from the leaderboard
DEFAULT_WHALES = [
    # Placeholder wallets — replace with actual top traders from Polymarket leaderboard
    # Format: (address, label)
]

# Polymarket leaderboard API
LEADERBOARD_URL = "https://data-api.polymarket.com/leaderboard"
POSITIONS_URL = "https://data-api.polymarket.com/positions"


class WhaleTracker:
    """Track whale positions and generate copy-trade signals."""

    def __init__(self, whale_wallets: list = None):
        self._wallets: list = whale_wallets or []
        self._positions_cache: dict = {}  # {wallet: [positions]}
        self._previous_positions: dict = {}  # for change detection
        self._signals: list = []  # recent signals
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._poll_interval: float = 60.0  # seconds between polls
        self._last_leaderboard_fetch: float = 0
        self._leaderboard_interval: float = 3600.0  # refresh leaderboard every hour

    async def start(self):
        """Start the whale tracking loop."""
        if self._running:
            return
        self._running = True

        # Fetch initial whale list from leaderboard
        await self._refresh_leaderboard()

        if self._wallets:
            self._task = asyncio.create_task(self._poll_loop())
            logger.info(f"WhaleTracker started — monitoring {len(self._wallets)} wallets")
        else:
            logger.warning("WhaleTracker: no whale wallets to monitor")

    async def stop(self):
        """Stop the tracking loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("WhaleTracker stopped")

    def get_signals(self) -> list:
        """Get recent whale signals (last 10 minutes)."""
        cutoff = time.time() - 600  # 10 minutes
        return [s for s in self._signals if s.get("timestamp", 0) > cutoff]

    def get_whale_count(self) -> int:
        """How many whales are being tracked."""
        return len(self._wallets)

    def get_recent_moves(self, limit: int = 10) -> list:
        """Get most recent whale moves."""
        return self._signals[-limit:]

    # ─── Internal ───

    async def _refresh_leaderboard(self):
        """Fetch top traders from Polymarket leaderboard."""
        now = time.time()
        if now - self._last_leaderboard_fetch < self._leaderboard_interval and self._wallets:
            return

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Fetch top profitable traders
                resp = await client.get(LEADERBOARD_URL, params={
                    "limit": 30,
                    "sortBy": "pnl",
                    "sortDirection": "DESC",
                    "window": "all",
                })
                if resp.status_code == 200:
                    data = resp.json()
                    new_wallets = []
                    for entry in data:
                        address = entry.get("userAddress", "") or entry.get("address", "")
                        pnl = float(entry.get("pnl", 0) or 0)
                        volume = float(entry.get("volume", 0) or 0)
                        name = entry.get("username", "") or entry.get("name", address[:10])

                        # Only track profitable whales with significant volume
                        if address and pnl > 1000 and volume > 10000:
                            new_wallets.append({
                                "address": address,
                                "name": name,
                                "pnl": pnl,
                                "volume": volume,
                            })

                    if new_wallets:
                        self._wallets = new_wallets
                        logger.info(f"WhaleTracker: loaded {len(new_wallets)} whales from leaderboard")
                    self._last_leaderboard_fetch = now

        except Exception as e:
            logger.warning(f"WhaleTracker leaderboard fetch error: {e}")

    async def _poll_loop(self):
        """Main polling loop — check whale positions periodically."""
        while self._running:
            try:
                # Refresh leaderboard periodically
                await self._refresh_leaderboard()

                # Poll positions for each whale (parallel)
                async with httpx.AsyncClient(timeout=10) as client:
                    tasks = [
                        self._fetch_positions(client, w["address"], w.get("name", ""))
                        for w in self._wallets[:20]  # limit to top 20 to avoid rate limits
                    ]
                    await asyncio.gather(*tasks, return_exceptions=True)

                # Detect consensus (multiple whales same direction)
                self._detect_consensus()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"WhaleTracker poll error: {e}")

            await asyncio.sleep(self._poll_interval)

    async def _fetch_positions(self, client: httpx.AsyncClient, wallet: str, label: str):
        """Fetch positions for a single whale and detect changes."""
        try:
            resp = await client.get(POSITIONS_URL, params={
                "user": wallet,
                "sizeThreshold": 0.5,
                "limit": 20,
                "sortBy": "CURRENT",
                "sortDirection": "DESC",
            })
            if resp.status_code != 200:
                return

            positions = resp.json()
            current_pos = {}
            for p in positions:
                asset = p.get("asset", "")
                if asset:
                    current_pos[asset] = {
                        "title": p.get("title", ""),
                        "outcome": p.get("outcome", ""),
                        "size": float(p.get("size", 0) or 0),
                        "currentValue": float(p.get("currentValue", 0) or 0),
                        "curPrice": float(p.get("curPrice", 0) or 0),
                        "percentPnl": float(p.get("percentPnl", 0) or 0),
                    }

            # Compare with previous positions to detect changes
            prev_pos = self._previous_positions.get(wallet, {})

            for asset, data in current_pos.items():
                prev = prev_pos.get(asset)
                if prev is None and data["currentValue"] > 100:
                    # New position opened
                    self._signals.append({
                        "type": "NEW_POSITION",
                        "whale": label,
                        "wallet": wallet[:10] + "...",
                        "title": data["title"],
                        "outcome": data["outcome"],
                        "size": data["currentValue"],
                        "price": data["curPrice"],
                        "asset": asset,
                        "timestamp": time.time(),
                    })
                    logger.info(f"🐋 {label}: NEW ${data['currentValue']:.0f} on '{data['title'][:40]}'")

                elif prev and data["currentValue"] > prev["currentValue"] * 1.5:
                    # Significant size increase (>50%)
                    self._signals.append({
                        "type": "SIZE_INCREASE",
                        "whale": label,
                        "wallet": wallet[:10] + "...",
                        "title": data["title"],
                        "outcome": data["outcome"],
                        "old_size": prev["currentValue"],
                        "new_size": data["currentValue"],
                        "price": data["curPrice"],
                        "asset": asset,
                        "timestamp": time.time(),
                    })

            # Detect exits (was in prev, not in current)
            for asset, prev_data in prev_pos.items():
                if asset not in current_pos and prev_data["currentValue"] > 100:
                    self._signals.append({
                        "type": "EXIT",
                        "whale": label,
                        "wallet": wallet[:10] + "...",
                        "title": prev_data["title"],
                        "outcome": prev_data["outcome"],
                        "size": prev_data["currentValue"],
                        "timestamp": time.time(),
                    })

            self._previous_positions[wallet] = current_pos
            self._positions_cache[wallet] = current_pos

            # Trim old signals (keep last 100)
            if len(self._signals) > 100:
                self._signals = self._signals[-100:]

        except Exception as e:
            logger.debug(f"WhaleTracker fetch error for {label}: {e}")

    def _detect_consensus(self):
        """Detect when multiple whales bet on the same market/direction."""
        # Group recent signals by market
        recent = [s for s in self._signals if s.get("timestamp", 0) > time.time() - 300]
        market_bets = {}

        for s in recent:
            if s["type"] in ("NEW_POSITION", "SIZE_INCREASE"):
                key = s.get("title", "")
                if key not in market_bets:
                    market_bets[key] = []
                market_bets[key].append(s)

        # Flag consensus (2+ whales same market)
        for title, bets in market_bets.items():
            if len(bets) >= 2:
                whales = [b["whale"] for b in bets]
                total_size = sum(b.get("size", 0) or b.get("new_size", 0) for b in bets)

                # Check if already signaled
                existing = [s for s in self._signals
                            if s.get("type") == "CONSENSUS" and s.get("title") == title
                            and s.get("timestamp", 0) > time.time() - 300]
                if not existing:
                    self._signals.append({
                        "type": "CONSENSUS",
                        "title": title,
                        "whales": whales,
                        "total_size": total_size,
                        "bet_count": len(bets),
                        "outcome": bets[0].get("outcome", ""),
                        "asset": bets[0].get("asset", ""),
                        "price": bets[0].get("price", 0),
                        "timestamp": time.time(),
                    })
                    logger.info(
                        f"🐋🐋 CONSENSUS: {len(whales)} whales on '{title[:40]}' "
                        f"(${total_size:,.0f} total)"
                    )
