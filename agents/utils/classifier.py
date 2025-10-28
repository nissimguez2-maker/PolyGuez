"""Market Category Classifier - Filters markets by information edge potential"""

from typing import Literal, Optional
import re
from collections import Counter

CategoryType = Literal[
    'politics', 'finance', 'tech', 'business', 'crypto',
    'geopolitics', 'legal', 'science', 'sports',
    'entertainment', 'weather', 'pop_culture', 'other'
]


class MarketClassifier:
    """Classifies markets by information content and edge potential"""

    # Keyword patterns for category detection
    KEYWORD_PATTERNS = {
        'politics': [
            r'\b(election|president|senator|congress|legislature|political|vote|ballot|campaign)\b',
            r'\b(democrat|republican|party|cabinet|appointment|governor|mayor)\b',
            r'\b(poll|primary|caucus|inauguration|biden|trump)\b'
        ],

        'finance': [
            r'\b(fed|federal reserve|interest rate|inflation|cpi|gdp|recession)\b',
            r'\b(stock market|s&p|dow|nasdaq|treasury|bond|yield)\b',
            r'\b(unemployment|jobs report|earnings|economy|economic)\b'
        ],

        'tech': [
            r'\b(apple|google|microsoft|meta|amazon|tesla|nvidia|openai)\b',
            r'\b(ai|artificial intelligence|chatgpt|product launch|iphone)\b',
            r'\b(antitrust|regulation|fcc|fda|approval|tech)\b',
            r'\b(ipo|acquisition|merger|valuation|startup)\b'
        ],

        'business': [
            r'\b(ceo|executive|earnings|revenue|profit|bankruptcy)\b',
            r'\b(corporate|company|shareholder|board|director)\b',
            r'\b(merger|acquisition|restructuring|layoff|business)\b'
        ],

        'crypto': [
            r'\b(bitcoin|ethereum|crypto|btc|eth|blockchain)\b',
            r'\b(etf|sec approval|regulation|exchange|coinbase)\b',
            r'\b(defi|nft|web3|protocol|solana)\b'
        ],

        'geopolitics': [
            r'\b(war|conflict|military|invasion|peace|treaty)\b',
            r'\b(nato|un|china|russia|israel|ukraine|taiwan)\b',
            r'\b(sanctions|diplomacy|alliance|nuclear)\b'
        ],

        'legal': [
            r'\b(court|supreme court|trial|verdict|ruling|judge)\b',
            r'\b(lawsuit|litigation|settlement|conviction|appeal)\b',
            r'\b(legal|law|justice|prosecutor|attorney)\b'
        ],

        'science': [
            r'\b(research|study|clinical trial|fda approval|drug)\b',
            r'\b(vaccine|treatment|cure|discovery|breakthrough)\b',
            r'\b(nobel|scientist|peer review|publication)\b'
        ],

        'sports': [
            r'\b(nfl|nba|mlb|nhl|fifa|olympics|championship|playoff)\b',
            r'\b(super bowl|world series|finals|game|match|team)\b',
            r'\b(player|athlete|coach|season|league)\b'
        ],

        'entertainment': [
            r'\b(oscar|grammy|emmy|award|nominee|movie|film)\b',
            r'\b(box office|album|song|actor|actress|celebrity)\b',
            r'\b(netflix|disney|streaming|tv show|concert)\b'
        ],

        'weather': [
            r'\b(hurricane|tornado|storm|temperature|rainfall)\b',
            r'\b(weather|climate|forecast|snow|precipitation)\b',
            r'\b(flood|drought|heat wave|cold snap)\b'
        ],

        'pop_culture': [
            r'\b(viral|trending|meme|influencer|tiktok)\b',
            r'\b(kardashian|celebrity gossip|reality tv)\b',
            r'\b(twitter|social media|instagram)\b'
        ]
    }

    # Skill weights: how much information edge matters (0.0-1.0)
    SKILL_WEIGHTS = {
        'politics': 0.85,      # HIGH: polling, insider knowledge, policy analysis
        'finance': 0.80,       # HIGH: economic indicators, fed decisions
        'tech': 0.75,          # HIGH: product roadmaps, regulatory filings
        'business': 0.75,      # HIGH: earnings, exec moves, strategic announcements
        'crypto': 0.70,        # MODERATE-HIGH: protocol developments, regulations
        'geopolitics': 0.65,   # MODERATE: intelligence reports, diplomatic cables
        'legal': 0.70,         # MODERATE-HIGH: court filings, precedent analysis
        'science': 0.65,       # MODERATE: peer review, clinical trials
        'sports': 0.30,        # LOW: high variance, physical randomness
        'entertainment': 0.35, # LOW: subjective taste, insider voting
        'weather': 0.40,       # LOW: chaotic system, professional models dominate
        'pop_culture': 0.25,   # VERY LOW: random viral dynamics
        'other': 0.50          # NEUTRAL
    }

    @classmethod
    def classify_market(cls, market) -> dict:
        """Classify market and return category with confidence"""
        # Handle both SimpleMarket and tuple (from RAG)
        if isinstance(market, tuple):
            text = f"{market[0].metadata.get('question', '')} {market[0].page_content}".lower()
        else:
            text = f"{market.question} {market.description}".lower()

        scores = {}
        for category, patterns in cls.KEYWORD_PATTERNS.items():
            score = 0
            for pattern in patterns:
                matches = len(re.findall(pattern, text, re.IGNORECASE))
                score += matches
            scores[category] = score

        # Get top category
        if max(scores.values()) == 0:
            category = 'other'
            confidence = 0.3
        else:
            category = max(scores, key=scores.get)
            total = sum(scores.values())
            confidence = scores[category] / total if total > 0 else 0

        skill_weight = cls.SKILL_WEIGHTS.get(category, 0.5)

        return {
            'category': category,
            'confidence': confidence,
            'skill_weight': skill_weight,
            'should_trade': skill_weight >= 0.65
        }

    @classmethod
    def filter_by_information_edge(cls, markets: list,
                                   min_skill_weight: float = 0.65) -> list:
        """Filter markets to only high-information-edge categories"""
        filtered = []

        for market in markets:
            classification = cls.classify_market(market)

            if classification['skill_weight'] >= min_skill_weight:
                # Attach classification metadata
                if hasattr(market, '__dict__'):
                    market.category = classification['category']
                    market.skill_weight = classification['skill_weight']
                filtered.append(market)

        return filtered

    @classmethod
    def get_category_summary(cls, markets: list) -> dict:
        """Get summary statistics by category"""
        categories = []
        for market in markets:
            classification = cls.classify_market(market)
            categories.append(classification['category'])

        return dict(Counter(categories))
