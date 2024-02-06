"""Common functions for all providers."""

import fake_useragent


def gen_user_agent() -> str:
    """Generate a random user agent."""
    default_ua = "Mozilla/5.0 (X11; Linux x86_64; rv:000.0) Gecko/20100101 Firefox/000.0"
    ua = fake_useragent.UserAgent(platforms=["pc"])
    return ua.random or default_ua
