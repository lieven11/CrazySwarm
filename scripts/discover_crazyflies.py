#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from crazyswarm_app.vehicles._cflib_link import CflibCrazyflieLink


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explicit read-only Crazyradio scan; never connects or arms"
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="required acknowledgement that a radio scan will be performed",
    )
    arguments = parser.parse_args()
    if not arguments.scan:
        parser.error("no radio action taken; pass --scan for an explicit discovery scan")
    uris = CflibCrazyflieLink.discover()
    print(json.dumps({"operation": "DISCOVERY_ONLY", "uris": uris}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
