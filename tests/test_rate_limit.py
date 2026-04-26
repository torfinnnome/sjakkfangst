"""Tests for rate limiter."""

import time

import pytest

from rate_limit import RateLimiter, MAX_REQUESTS_PER_IP, MAX_REQUESTS_GLOBAL, WINDOW_SECONDS


@pytest.fixture
def limiter():
    return RateLimiter()


class TestRateLimiter:
    def test_allows_first_request(self, limiter):
        allowed, reason, wait = limiter.check("1.2.3.4")
        assert allowed is True
        assert reason is None
        assert wait == 0.0

    def test_allows_up_to_per_ip_limit(self, limiter):
        for _ in range(MAX_REQUESTS_PER_IP):
            allowed, _, _ = limiter.check("1.2.3.4")
            assert allowed is True

        # Next request should be blocked
        allowed, reason, wait = limiter.check("1.2.3.4")
        assert allowed is False
        assert reason is not None
        assert wait > 0

    def test_different_ips_have_separate_limits(self, limiter):
        # Fill up IP 1
        for _ in range(MAX_REQUESTS_PER_IP):
            limiter.check("1.2.3.4")

        # IP 2 should still be allowed
        allowed, _, _ = limiter.check("5.6.7.8")
        assert allowed is True

    def test_global_limit_applies_across_ips(self, limiter):
        # Fill up global limit with different IPs
        for i in range(MAX_REQUESTS_GLOBAL):
            allowed, _, _ = limiter.check(f"10.{i}.0.1")
            assert allowed is True

        # Next IP should be blocked by global limit
        allowed, reason, wait = limiter.check("99.99.99.99")
        assert allowed is False
        assert "all users" in reason.lower()

    def test_per_ip_blocks_before_global(self, limiter):
        # Fill IP 1 to its limit
        for _ in range(MAX_REQUESTS_PER_IP):
            limiter.check("1.2.3.4")

        # IP 1 should be blocked, but reason should be per-IP
        allowed, reason, _ = limiter.check("1.2.3.4")
        assert allowed is False
        assert "all users" not in reason.lower()

    def test_requests_expire_after_window(self, limiter, monkeypatch):
        # Monkeypatch time so we can simulate expiry
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)

        for _ in range(MAX_REQUESTS_PER_IP):
            limiter.check("1.2.3.4")

        # Advance time past window
        monkeypatch.setattr(time, "time", lambda: now + WINDOW_SECONDS + 1)

        # Should be allowed again
        allowed, _, _ = limiter.check("1.2.3.4")
        assert allowed is True

    def test_wait_seconds_decreases_over_time(self, limiter, monkeypatch):
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)

        for _ in range(MAX_REQUESTS_PER_IP):
            limiter.check("1.2.3.4")

        # Wait should be close to full window
        _, _, wait = limiter.check("1.2.3.4")
        assert wait > 25  # roughly half the window

        # Advance halfway
        monkeypatch.setattr(time, "time", lambda: now + WINDOW_SECONDS / 2)
        _, _, wait_half = limiter.check("1.2.3.4")
        assert wait_half < wait
