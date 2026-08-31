from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Literal

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "Ambrosia Health",
    instructions=(
        "Read bounded personal-health aggregates only. Do not diagnose, prescribe, expose raw samples, "
        "or make writes. Every conclusion must cite dates and coverage. Association is not causation."
    ),
)


API_ROOT = os.environ.get("AMBROSIA_API_URL", "http://127.0.0.1:8787/api")


def _get(path: str, params: dict | None = None) -> dict:
    with httpx.Client(timeout=30) as client:
        response = client.get(f"{API_ROOT}{path}", params=params)
        response.raise_for_status()
        return response.json()


@mcp.tool()
def get_health_overview(as_of: str | None = None) -> dict:
    """Get the seven-day overview and preceding personal baseline, including dates and coverage."""
    return _get("/home", {"date": as_of} if as_of else None)


@mcp.tool()
def get_domain_summary(
    domain: Literal["fitness", "sleep", "nutrition"],
    range_name: Literal["7d", "28d", "90d"] = "28d",
) -> dict:
    """Get bounded daily aggregates for one dashboard domain."""
    return _get(f"/{domain}", {"range": range_name})


@mcp.tool()
def compare_periods(
    metric: Literal[
        "steps", "active_minutes", "zone_minutes", "workouts", "workout_duration", "distance",
        "sleep_duration", "resting_hr", "hrv", "spo2", "respiratory_rate", "weight",
        "calories", "protein", "hydration",
    ],
    as_of: str | None = None,
) -> dict:
    """Compare the latest seven days with the preceding 28 valid personal days for one metric."""
    return _get(f"/compare/{metric}", {"date": as_of} if as_of else None)


@mcp.tool()
def analyze_relationship(
    relationship: Literal["sleep_hrv", "sleep_rhr", "load_hrv", "nutrition_weight"],
) -> dict:
    """Get one predeclared exploratory relationship with paired-day count and bootstrap interval."""
    return _get(f"/relationships/{relationship}")


@mcp.tool()
def get_profile_and_data_quality() -> dict:
    """Get confirmed profile preferences and aggregate data coverage, without identifiers or paths."""
    return _get("/profile-and-quality")


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
