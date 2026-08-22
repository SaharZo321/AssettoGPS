"""Development-only AssettoGPS server with generated driving telemetry."""

from pathlib import Path

import server
from mock_telemetry import MockTelemetryGenerator


DEVELOPMENT_ROUTE = (
    Path(__file__).resolve().parent
    / "dev_assets"
    / "srp-development-route.json"
)
mock_generator = MockTelemetryGenerator(DEVELOPMENT_ROUTE)

# Configure the shared application before Uvicorn runs its startup hooks.
server.telemetry_reader = mock_generator.get_frame
server.telemetry_reset = mock_generator.reset
server.ac_watchdog_enabled = False


def main(argv=None):
    print("[Development] Generated telemetry is enabled.")
    server.main(argv)


if __name__ == "__main__":
    main()
