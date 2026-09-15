"""Tests for main.py's process-level setup helpers."""

from __future__ import annotations

import socket

from planner_agent.main import _prefer_ipv4_dns


def test_prefer_ipv4_dns_forces_af_inet(monkeypatch):
    """Every getaddrinfo call, regardless of requested family, resolves AF_INET only."""
    calls: list[int] = []

    def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        calls.append(family)
        return []

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    _prefer_ipv4_dns()

    socket.getaddrinfo("example.com", 443)  # default family=AF_UNSPEC
    socket.getaddrinfo("example.com", 443, family=socket.AF_INET6)

    assert calls == [socket.AF_INET, socket.AF_INET]
