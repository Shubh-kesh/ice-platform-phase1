"""
Rate limiting configuration using slowapi (ASGI-compatible wrapper for ratelimit).

Protects authentication endpoints from brute force attacks.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# Rate limiter instance; can be used as dependency or decorator
limiter = Limiter(key_func=get_remote_address)

# Rate limit constants
AUTH_RATE_LIMIT = "5/minute"  # 5 attempts per minute per IP
REFRESH_RATE_LIMIT = "10/minute"  # 10 refresh attempts per minute per IP
