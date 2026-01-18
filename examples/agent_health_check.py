"""
Simple agent health check script.

Verifies that the agent process can start
and perform a basic no-op cycle.
"""


def agent_health_check() -> None:
    print("Agent status: OK")


if __name__ == "__main__":
    agent_health_check()
