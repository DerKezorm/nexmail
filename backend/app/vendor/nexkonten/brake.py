"""The sign-in brake in memory, and the sender's address behind a proxy.

Every app runs one worker, so the brake lives in its memory (a restart forgets it; the lock of an account after ten
wrong passwords is in the database, ``Store.is_locked``). An attempt is checked and counted in one step (``claim``):
many attempts at once cannot all pass before the first failure is counted.

Counts as ``login.attempt_key`` gives them, two per attempt: the sender (30 free) and the account or what was typed
(5 free). After the free ones each further failure waits longer: 5 seconds, doubled each time, at most 15 minutes. A
count is forgotten an hour after its last failure; at most 50 000 counts are kept.

The sender's address: behind proxies the app trusts (``<APP>_TRUSTED_PROXIES``, CIDR) the rightmost hop of
``X-Forwarded-For`` that is not one of them; IPv6 counts per /64. Without trusted proxies the peer of the connection.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from dataclasses import dataclass, field

FREE = {"sender": 30, "account": 5, "typed": 5}
FREE_OTHER = 5
FIRST_WAIT = 5.0
LONGEST_WAIT = 15 * 60.0
FORGET_AFTER = 3600.0
MAX_COUNTS = 50_000


@dataclass
class _Count:
    failures: int = 0
    last: float = 0.0
    blocked_until: float = 0.0


@dataclass
class Brake:
    """One per process (``BRAKE``)."""

    counts: dict[str, _Count] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def _free(self, key: str) -> int:
        return FREE.get(key.partition(":")[0], FREE_OTHER)

    def _sweep(self, now: float) -> None:
        if len(self.counts) < MAX_COUNTS:
            return
        for key in [key for key, count in self.counts.items() if now - count.last > FORGET_AFTER]:
            self.counts.pop(key, None)
        while len(self.counts) >= MAX_COUNTS:
            self.counts.pop(next(iter(self.counts)))

    def wait(self, keys: tuple[str, ...] | list[str], now: float | None = None) -> float:
        """Seconds to wait before the next attempt may run (0: it may), without counting."""
        moment = time.monotonic() if now is None else now
        with self.lock:
            waits = [
                count.blocked_until - moment
                for key in keys
                if (count := self.counts.get(key)) is not None and moment - count.last <= FORGET_AFTER
            ]
        return max([0.0, *waits])

    def failed(self, keys: tuple[str, ...] | list[str], now: float | None = None) -> float:
        """Count a failure at every key; the longest wait that follows."""
        moment = time.monotonic() if now is None else now
        longest = 0.0
        with self.lock:
            self._sweep(moment)
            for key in keys:
                count = self.counts.get(key)
                if count is None or moment - count.last > FORGET_AFTER:
                    count = self.counts[key] = _Count()
                count.failures += 1
                count.last = moment
                over = count.failures - self._free(key)
                if over > 0:
                    wait = min(FIRST_WAIT * 2 ** (over - 1), LONGEST_WAIT)
                    count.blocked_until = moment + wait
                    longest = max(longest, wait)
        return longest

    def claim(self, keys: tuple[str, ...] | list[str], now: float | None = None) -> float:
        """Check and count in one step: the wait when the attempt must not run (nothing counted then), else 0 and
        the attempt counted as a failure until ``succeeded``."""
        moment = time.monotonic() if now is None else now
        waiting = self.wait(keys, moment)
        if waiting > 0:
            return waiting
        self.failed(keys, moment)
        return 0.0

    def succeeded(self, keys: tuple[str, ...] | list[str]) -> None:
        """The attempt was right: its account's count starts anew (the sender's stays, it may try others)."""
        with self.lock:
            for key in keys:
                if not key.startswith("sender:"):
                    self.counts.pop(key, None)

    def forget(self) -> None:
        with self.lock:
            self.counts.clear()


BRAKE = Brake()


def _networks(trusted: str | list[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    entries = trusted.split(",") if isinstance(trusted, str) else trusted
    found = []
    for entry in entries:
        text = entry.strip()
        if text:
            try:
                found.append(ipaddress.ip_network(text, strict=False))
            except ValueError:
                continue
    return found


def _counted(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is None:
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address.ipv4_mapped or address) if isinstance(address, ipaddress.IPv6Address) else str(address)


def client_address(peer: str, forwarded_for: str, trusted: str | list[str]) -> str:
    """The sender as the brake counts it."""
    networks = _networks(trusted)
    try:
        current = ipaddress.ip_address((peer or "").strip())
    except ValueError:
        return peer or "unknown"
    if not networks or not any(current in network for network in networks):
        return _counted(current)
    for hop in reversed([part.strip() for part in (forwarded_for or "").split(",") if part.strip()]):
        try:
            address = ipaddress.ip_address(hop)
        except ValueError:
            return _counted(current)
        if not any(address in network for network in networks):
            return _counted(address)
        current = address
    return _counted(current)
