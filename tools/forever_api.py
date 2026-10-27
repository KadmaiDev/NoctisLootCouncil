"""Writes harness/forever_api.json: the names of the functions and events the Forever client has,
which the tests check the fake client and the addon against.

Functions come from forever-addon-kit's capture of the live client (data/forever_api.json),
events from forever-addon-dev's API documentation dump (data/api.json). Both MIT; their notices
are in harness/forever_api.LICENSE.

    python tools/forever_api.py <forever-addon-kit folder> <forever-addon-dev folder>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "harness" / "forever_api.json"


def main(kit: Path, dev: Path) -> None:
    cap = json.loads((kit / "data" / "forever_api.json").read_text(encoding="utf-8"))
    docs = json.loads((dev / "data" / "api.json").read_text(encoding="utf-8"))
    events = sorted({e["LiteralName"] for system in docs["systems"].values()
                     for e in system.get("Events", [])})
    names = {
        "about": "Names only, from forever-addon-kit (functions) and forever-addon-dev (events); "
                 "see forever_api.LICENSE. Regenerate with tools/forever_api.py.",
        "client": cap["client"],
        "events_build": docs["build"]["build"],
        "globals": sorted(cap["functions"]),
        "namespaces": {ns: sorted(fns) for ns, fns in sorted(cap["namespaces"].items())},
        "events": events,
    }
    OUT.write_text(json.dumps(names, indent=0) + "\n", encoding="utf-8")
    print(f"{OUT.name}: {len(names['globals'])} globals, {len(names['namespaces'])} namespaces, "
          f"{len(events)} events")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
