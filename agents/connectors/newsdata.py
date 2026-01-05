from __future__ import annotations

from datetime import datetime
import os

import requests

from agents.utils.objects import Article


class NewsDataNews:
    def __init__(self) -> None:
        self.api_key = os.getenv("NEWSDATA_API_KEY")
        self.base_url = "https://newsdata.io/api/1/news"
        self.language = "en"
        self.country = "us"

    def get_articles_for_cli_keywords(self, keywords: str) -> "list[Article]":
        query_words = keywords.split(",")
        all_articles = self.get_articles_for_options(query_words)
        article_objects: list[Article] = []
        for _, articles in all_articles.items():
            for article in articles:
                article_objects.append(Article(**article))
        return article_objects

    def get_articles_for_options(
        self,
        market_options: "list[str]",
        date_start: datetime = None,
        date_end: datetime = None,
    ) -> dict[str, list[dict]]:
        all_articles: dict[str, list[dict]] = {}
        for option in market_options:
            params = {
                "apikey": self.api_key,
                "q": option.strip(),
                "language": self.language,
                "country": self.country,
                "size": 10,
            }
            if date_start:
                params["from_date"] = f"{date_start:%Y-%m-%d}"
            if date_end:
                params["to_date"] = f"{date_end:%Y-%m-%d}"

            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            results = response.json().get("results", [])
            all_articles[option] = [self._normalize_article(item) for item in results]

        return all_articles

    def _normalize_article(self, item: dict) -> dict:
        creator = item.get("creator")
        if isinstance(creator, list):
            creator = creator[0] if creator else None
        source_id = item.get("source_id")
        return {
            "source": {"name": source_id} if source_id else None,
            "author": creator,
            "title": item.get("title"),
            "description": item.get("description"),
            "url": item.get("link"),
            "urlToImage": item.get("image_url"),
            "publishedAt": item.get("pubDate"),
            "content": item.get("content"),
        }
