"""Market metrics and universe analysis"""

from collections import Counter
from agents.utils.classifier import MarketClassifier


class MarketMetrics:
    """Analytics for market selection and performance by category"""

    @staticmethod
    def analyze_market_universe(polymarket):
        """Generate insights on available markets"""
        all_markets = polymarket.get_all_markets()

        # Classify all markets
        categorized = {}
        for market in all_markets:
            classification = MarketClassifier.classify_market(market)
            category = classification['category']

            if category not in categorized:
                categorized[category] = []

            volume = float(market.volume) if hasattr(market, 'volume') and market.volume else 0
            liquidity = float(market.liquidity) if hasattr(market, 'liquidity') and market.liquidity else 0

            categorized[category].append({
                'market': market,
                'skill_weight': classification['skill_weight'],
                'volume': volume,
                'liquidity': liquidity
            })

        # Generate report
        print("\n" + "="*70)
        print("MARKET UNIVERSE ANALYSIS")
        print("="*70 + "\n")

        total_markets = len(all_markets)
        print(f"Total Markets: {total_markets}\n")

        # Category breakdown
        for category in sorted(categorized.keys()):
            markets = categorized[category]
            total = len(markets)
            total_volume = sum(m['volume'] for m in markets)
            avg_skill = sum(m['skill_weight'] for m in markets) / total if total > 0 else 0

            print(f"{category.upper():20} | Markets: {total:3} | "
                  f"Volume: ${total_volume:>12,.0f} | "
                  f"Skill Weight: {avg_skill:.2f}")

        # Focus recommendations
        print("\n" + "="*70)
        print("RECOMMENDED FOCUS AREAS (High Information Edge)")
        print("="*70 + "\n")

        high_edge = {cat: markets for cat, markets in categorized.items()
                     if markets and markets[0]['skill_weight'] >= 0.65}

        for category, markets in sorted(high_edge.items(),
                                       key=lambda x: len(x[1]),
                                       reverse=True):
            total_vol = sum(m['volume'] for m in markets)
            print(f"✓ {category.upper():15} | {len(markets):3} markets | ${total_vol:>12,.0f} volume")

        # Avoid categories
        print("\n" + "="*70)
        print("AVOID CATEGORIES (Low Information Edge)")
        print("="*70 + "\n")

        low_edge = {cat: markets for cat, markets in categorized.items()
                   if markets and markets[0]['skill_weight'] < 0.50}

        for category, markets in sorted(low_edge.items()):
            total_vol = sum(m['volume'] for m in markets)
            print(f"✗ {category.upper():15} | {len(markets):3} markets | ${total_vol:>12,.0f} volume")

        print("\n" + "="*70 + "\n")

        return categorized
