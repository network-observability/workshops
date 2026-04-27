"""nobs — network observability operator toolkit.

Importing the `nobs` package triggers workshop self-registration via the
`autocon5_workshop` side-effect import below. After that, code can read
`nobs.workshops.REGISTRY` to discover the active workshop set.

When entry-points discovery is added later, this side-effect import
becomes a loop over `entry_points(group="nobs.workshops")`.
"""
from __future__ import annotations

__version__ = "0.1.0"

import autocon5_workshop  # noqa: F401  - registers WORKSHOP via side-effect
