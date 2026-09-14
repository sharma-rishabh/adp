"""Shared trigger/marker strings for the heartbeat protocol.

The heartbeat *emits* these (as message text) and the orchestrator *routes*
on them, so they live in one neutral module instead of being duplicated —
and to avoid a heartbeat<->orchestrator import cycle (heartbeat already
imports Orchestrator).
"""

from __future__ import annotations

NUDGE_TRIGGER = "[heartbeat-nudge]"
EOD_TRIGGER = "[eod-reflection]"
SKIP_MARKER = "[skip]"

# IncomingMessage.adapter_name values used for synthetic heartbeat messages —
# NOT real user activity, so the orchestrator excludes them when tracking
# "did the user reply" for nudge backoff.
HEARTBEAT_ADAPTER = "heartbeat"
EOD_ADAPTER = "eod-reflection"

# Sandbox file (root-level) holding the /pause expiry, written by the
# orchestrator's /pause command and read by the heartbeat before firing.
PAUSED_UNTIL_FILE = "paused_until.txt"
