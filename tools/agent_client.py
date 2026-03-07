#!/usr/bin/env python3
"""
agent_client.py — Python client for the Norrust TCP agent server.

Usage:
    # Start game with: love norrust_love -- --agent-server
    # Then run:
    python3 tools/agent_client.py

Protocol: line-based TCP on localhost:9876
    get_state        → JSON state
    get_faction      → active faction number
    check_winner     → winner faction (-1 if none)
    ai_turn FACTION  → run AI for faction
    {"action":...}   → ActionRequest JSON, returns result code
"""

import json
import socket
import sys


class NorRustClient:
    """TCP client for the Norrust agent server."""

    def __init__(self, host="localhost", port=9876):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        self._buf = b""

    def _send_recv(self, command: str) -> str:
        """Send a command line and receive the response line."""
        self.sock.sendall((command + "\n").encode())
        # Read until we get a complete line
        while b"\n" not in self._buf:
            data = self.sock.recv(65536)
            if not data:
                raise ConnectionError("Server closed connection")
            self._buf += data
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode()

    def get_state(self) -> dict:
        """Get the full game state as a parsed dict."""
        raw = self._send_recv("get_state")
        return json.loads(raw)

    def get_active_faction(self) -> int:
        """Get the currently active faction (0 or 1)."""
        return int(self._send_recv("get_faction"))

    def check_winner(self) -> int:
        """Check if there's a winner. Returns -1 if no winner yet."""
        return int(self._send_recv("check_winner"))

    def send_action(self, action: dict) -> int:
        """Send an ActionRequest and return the result code (0 = success)."""
        return int(self._send_recv(json.dumps(action)))

    def end_turn(self) -> int:
        """Convenience: send EndTurn action."""
        return self.send_action({"action": "EndTurn"})

    def move_unit(self, unit_id: int, col: int, row: int) -> int:
        """Convenience: move a unit to a hex."""
        return self.send_action({"action": "Move", "unit_id": unit_id, "col": col, "row": row})

    def attack(self, attacker_id: int, defender_id: int) -> int:
        """Convenience: attack with one unit against another."""
        return self.send_action({"action": "Attack", "attacker_id": attacker_id, "defender_id": defender_id})

    def ai_turn(self, faction: int) -> int:
        """Run the built-in AI for the given faction."""
        return int(self._send_recv(f"ai_turn {faction}"))

    def close(self):
        """Close the connection."""
        self.sock.close()


def main():
    """Demo: connect, show state, send EndTurn, show updated state."""
    print("Connecting to Norrust agent server...")
    try:
        client = NorRustClient()
    except ConnectionRefusedError:
        print("ERROR: Could not connect. Start the game with: love norrust_love -- --agent-server")
        sys.exit(1)

    print("Connected!\n")

    # Get and display state
    state = client.get_state()
    faction = client.get_active_faction()
    winner = client.check_winner()

    print(f"Turn: {state.get('turn', '?')}")
    print(f"Active faction: {faction}")
    print(f"Winner: {winner} (-1 = none)")
    print(f"Units: {len(state.get('units', []))}")
    print(f"Gold: {state.get('gold', [])}")

    units = state.get("units", [])
    for u in units[:6]:
        print(f"  [{u['id']}] {u['def_id']} f{u['faction']} ({u['col']},{u['row']}) hp={u['hp']}/{u['max_hp']}")
    if len(units) > 6:
        print(f"  ... and {len(units) - 6} more")

    # Send EndTurn
    print("\nSending EndTurn...")
    rc = client.end_turn()
    print(f"Result: {rc} (0 = success)")

    # Show updated state
    state2 = client.get_state()
    faction2 = client.get_active_faction()
    print(f"\nAfter EndTurn:")
    print(f"Turn: {state2.get('turn', '?')}")
    print(f"Active faction: {faction2}")

    client.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
