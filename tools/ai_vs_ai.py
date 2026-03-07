#!/usr/bin/env python3
"""
ai_vs_ai.py — Run a complete AI vs AI game over the TCP agent server.

Usage:
    # Start game with: love norrust_love -- --agent-server
    # Select a preset scenario (e.g. Crossing)
    # Then run:
    python3 tools/ai_vs_ai.py [--max-turns N] [--delay SECONDS]
"""

import argparse
import sys
import time

# Import the client from the same tools directory
sys.path.insert(0, sys.path[0])
from agent_client import NorRustClient


def run_ai_vs_ai(max_turns: int = 200, delay: float = 0.0):
    print("Connecting to Norrust agent server...")
    try:
        client = NorRustClient()
    except ConnectionRefusedError:
        print("ERROR: Could not connect. Start the game with: love norrust_love -- --agent-server")
        sys.exit(1)

    print("Connected! Starting AI vs AI game.\n")

    state = client.get_state()
    turn = state.get("turn", 1)

    for i in range(max_turns):
        faction = client.get_active_faction()
        state = client.get_state()
        turn = state.get("turn", "?")
        units = state.get("units", [])
        gold = state.get("gold", [0, 0])

        f0_units = sum(1 for u in units if u["faction"] == 0)
        f1_units = sum(1 for u in units if u["faction"] == 1)

        print(f"Turn {turn} | Faction {faction} | Units: {f0_units} vs {f1_units} | Gold: {gold[0]} / {gold[1]}")

        # Run AI for active faction
        client.ai_turn(faction)

        # Check for winner
        winner = client.check_winner()
        if winner != -1:
            state = client.get_state()
            units = state.get("units", [])
            f0_alive = sum(1 for u in units if u["faction"] == 0)
            f1_alive = sum(1 for u in units if u["faction"] == 1)
            print(f"\n{'='*40}")
            print(f"GAME OVER — Faction {winner} wins!")
            print(f"Final: {f0_alive} vs {f1_alive} units, turn {state.get('turn', '?')}")
            print(f"Rounds played: {i + 1}")
            print(f"{'='*40}")
            client.close()
            return

        if delay > 0:
            time.sleep(delay)

    print(f"\nMax turns ({max_turns}) reached without a winner.")
    client.close()


def main():
    parser = argparse.ArgumentParser(description="Run AI vs AI game over TCP")
    parser.add_argument("--max-turns", type=int, default=200, help="Safety limit (default: 200)")
    parser.add_argument("--delay", type=float, default=0.0, help="Delay between turns in seconds (default: 0)")
    args = parser.parse_args()

    run_ai_vs_ai(max_turns=args.max_turns, delay=args.delay)


if __name__ == "__main__":
    main()
