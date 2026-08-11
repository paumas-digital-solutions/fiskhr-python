"""Public test utilities for downstream users of `fiskalhr`.

`MockCis` lets you test your F1 integration end to end — including request
validation and response-signature verification — without ever touching the
demo environment or owning a FINA certificate.
"""

from fiskalhr.testing.mock_cis import MockCis

__all__ = ["MockCis"]
