"""Croatian fiscalization for Python.

`fiskhr` covers both Croatian fiscalization regimes:

- **Fiskalizacija 1.0 (F1)** — real-time B2C receipt fiscalization against the
  Tax Administration's CIS service (`fiskhr.f1`).
- **Fiskalizacija 2.0 (F2)** — B2B eRacun: UBL 2.1 / HR CIUS 2025 documents and
  the eFiskalizacija / eIzvjestavanje messages (`fiskhr.f2`).

Shared building blocks (certificates, signing, transport, errors) live in
`fiskhr.core`.
"""

from fiskhr.core.certs import Certificate
from fiskhr.core.environment import Environment
from fiskhr.core.errors import FiskalizacijaError

__version__ = "0.0.1"

__all__ = [
    "Certificate",
    "Environment",
    "FiskalizacijaError",
    "__version__",
]
