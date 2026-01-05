from __future__ import annotations

from datetime import datetime
import os

import requests

from agents.utils.objects import Article


class MediaStackNews:
    def __init__(self) -> None:
        self.api_key = os.getenv("MEDIASTACK_API_KEY")
        self.base_url = "http://api.mediastack.com/v1/news"
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
                "access_key": self.api_key,
                "keywords": option.strip(),
                "languages": self.language,
                "countries": self.country,
                "sort": "published_desc",
                "limit": 10,
            }
            if date_start and date_end:
                params["date"] = f"{date_start:%Y-%m-%d},{date_end:%Y-%m-%d}"
            elif date_start:
                params["date"] = f"{date_start:%Y-%m-%d}"

            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json().get("data", [])
            all_articles[option] = [self._normalize_article(item) for item in data]

        return all_articles

    def _normalize_article(self, item: dict) -> dict:
        source_name = item.get("source")
        return {
            "source": {"name": source_name} if source_name else None,
            "author": item.get("author"),
            "title": item.get("title"),
            "description": item.get("description"),
            "url": item.get("url"),
            "urlToImage": item.get("image"),
            "publishedAt": item.get("published_at"),
            "content": None,
        }
