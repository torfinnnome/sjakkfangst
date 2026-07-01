"""Simple in-memory rate limiter with per-IP and global limits."""

import threading
import time
from typing import Optional, Tuple

# Configuration
MAX_REQUESTS_PER_IP = 2  # per minute per client
MAX_REQUESTS_GLOBAL = 6  # per minute across all clients
WINDOW_SECONDS = 60
SEARCH_MAX_REQUESTS = 1  # per 5s per client (search only)
SEARCH_WINDOW_SECONDS = 5


class RateLimiter:
    """Track request timestamps and enforce per-IP and global rate limits."""

    def __init__(self):
        self._lock = threading.Lock()
        self._ip_times: dict[str, list[float]] = {}
        self._global_times: list[float] = []

    def _prune(self, times: list[float], now: float) -> list[float]:
        return [t for t in times if now - t < WINDOW_SECONDS]

    def check(self, client_ip: str) -> Tuple[bool, Optional[str], float]:
        """Check whether a request from client_ip is allowed.

        Returns:
            (allowed, reason, wait_seconds)
            - allowed: True if request can proceed
            - reason: None if allowed, or descriptive text
            - wait_seconds: 0 if allowed, or seconds until next slot opens
        """
        now = time.time()

        with self._lock:
            # Clean up old entries
            self._global_times = self._prune(self._global_times, now)
            ip_times = self._ip_times.get(client_ip, [])
            ip_times = self._prune(ip_times, now)
            self._ip_times[client_ip] = ip_times

            # Check global limit
            if len(self._global_times) >= MAX_REQUESTS_GLOBAL:
                oldest = min(self._global_times)
                wait = WINDOW_SECONDS - (now - oldest)
                return False, "Too many requests from all users. Try again shortly.", max(wait, 0)

            # Check per-IP limit
            if len(ip_times) >= MAX_REQUESTS_PER_IP:
                oldest = min(ip_times)
                wait = WINDOW_SECONDS - (now - oldest)
                return False, "Too many requests. Please wait.", max(wait, 0)

            # Allow — record the timestamp
            self._global_times.append(now)
            ip_times.append(now)
            return True, None, 0.0


# Singleton
rate_limiter = RateLimiter()


class SearchRateLimiter:
    """Track search request timestamps and enforce per-IP rate limits.

    Allows 1 search request per 5 seconds per IP address. Uses the same
    sliding-window pattern as RateLimiter but with tighter limits since
    each search triggers an external scrape.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._ip_times: dict[str, list[float]] = {}

    def _prune(self, times: list[float], now: float) -> list[float]:
        return [t for t in times if now - t < SEARCH_WINDOW_SECONDS]

    def check(self, client_ip: str) -> Tuple[bool, float]:
        """Check whether a search request from client_ip is allowed.

        Returns:
            (allowed, wait_seconds)
            - allowed: True if request can proceed
            - wait_seconds: 0 if allowed, or seconds until next slot opens
        """
        now = time.time()

        with self._lock:
            ip_times = self._ip_times.get(client_ip, [])
            ip_times = self._prune(ip_times, now)
            self._ip_times[client_ip] = ip_times

            if len(ip_times) >= SEARCH_MAX_REQUESTS:
                oldest = min(ip_times)
                wait = SEARCH_WINDOW_SECONDS - (now - oldest)
                return False, max(wait, 0)

            ip_times.append(now)
            return True, 0.0


_search_limiter = SearchRateLimiter()
