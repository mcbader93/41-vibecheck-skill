"""Entry point of the /vibecheck skill: runs the bundled vibecheck CLI. Standard library only, Python 3.9+.

The core lives in the sibling folder `vibecheck/` (a generated copy of src/vibecheck made by tools/build.py).
The CLI creates the output folders for --out and --json when they are missing.
"""

import os
import sys

if sys.version_info < (3, 9):
    sys.stderr.write("The 41 vibe check needs Python 3.9 or newer (found %d.%d).\n" % sys.version_info[:2])
    raise SystemExit(3)

# Put this folder first so `import vibecheck` finds the bundled copy, wherever the skill was installed.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vibecheck.cli import main  # noqa: E402

raise SystemExit(main())
