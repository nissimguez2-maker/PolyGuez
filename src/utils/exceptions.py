class BotError(Exception):
    """Base exception for bot-related failures."""


class ValidationError(BotError):
    """Raised when input validation fails."""


class APIError(BotError):
    """Raised when external API calls fail."""

