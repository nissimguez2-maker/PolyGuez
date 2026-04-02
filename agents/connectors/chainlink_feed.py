"""Chainlink BTC/USD on-chain price feed — fallback when RTDS is unavailable.

Reads from the Polygon Chainlink aggregator contract via web3.
This is NOT the primary data path — RTDS is preferred for latency.
"""

from agents.utils.logger import get_logger, log_event

logger = get_logger("polyguez.chainlink_onchain")

# Polygon mainnet Chainlink BTC/USD aggregator proxy
_AGGREGATOR_ADDRESS = "0xc907E116054Ad103354f2D350FD2514433D57F6f"

# Minimal AggregatorV3Interface ABI — only what we need
_AGGREGATOR_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"internalType": "uint80", "name": "roundId", "type": "uint80"},
            {"internalType": "int256", "name": "answer", "type": "int256"},
            {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
            {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
            {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class ChainlinkOnChainFeed:
    """Read Chainlink BTC/USD price from Polygon aggregator contract."""

    def __init__(self, web3_instance=None, rpc_url="https://polygon.drpc.org"):
        self._web3 = web3_instance
        self._rpc_url = rpc_url
        self._contract = None
        self._decimals = None

    def _init_contract(self):
        if self._contract is not None:
            return
        if self._web3 is None:
            from web3 import Web3
            self._web3 = Web3(Web3.HTTPProvider(self._rpc_url))
        self._contract = self._web3.eth.contract(
            address=self._web3.to_checksum_address(_AGGREGATOR_ADDRESS),
            abi=_AGGREGATOR_ABI,
        )
        self._decimals = self._contract.functions.decimals().call()

    def get_latest_price(self):
        """Return (price_float, updated_at_timestamp) or (None, None) on error."""
        try:
            self._init_contract()
            round_data = self._contract.functions.latestRoundData().call()
            answer = round_data[1]
            updated_at = round_data[3]
            price = answer / (10 ** self._decimals)
            return (price, updated_at)
        except Exception as exc:
            log_event(logger, "chainlink_onchain_error", f"On-chain read failed: {exc}")
            return (None, None)
