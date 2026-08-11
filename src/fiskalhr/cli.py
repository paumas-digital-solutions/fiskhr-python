"""The ``fiskalhr`` command-line interface.

Phase 0 ships ``cert info``; ``zki``, ``validate``, ``echo``, and
``fiscalize`` arrive with the corresponding library phases.

P12 passwords are read from the ``FISKALHR_P12_PASSWORD`` environment variable
or prompted interactively — never accepted as a command-line argument, because
arguments are visible in the process list and shell history.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Sequence

from fiskalhr import __version__
from fiskalhr.core.certs import Certificate
from fiskalhr.core.errors import FiskalizacijaError

PASSWORD_ENV_VAR = "FISKALHR_P12_PASSWORD"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fiskalhr",
        description="Croatian fiscalization (F1 + F2) toolbox.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    cert_parser = subparsers.add_parser("cert", help="certificate utilities")
    cert_subparsers = cert_parser.add_subparsers(dest="cert_command", required=True)

    info_parser = cert_subparsers.add_parser(
        "info",
        help="inspect a P12 certificate",
        description=(
            "Load a P12/PFX file and print its subject, issuer, validity and OIB. "
            f"The password is taken from ${PASSWORD_ENV_VAR} or prompted."
        ),
    )
    info_parser.add_argument("path", help="path to the .p12/.pfx file")

    return parser


def _read_password() -> str:
    password = os.environ.get(PASSWORD_ENV_VAR)
    if password is not None:
        return password
    return getpass.getpass("P12 password: ")


def _cert_info(path: str) -> int:
    cert = Certificate.from_p12(path, _read_password())
    expired = "yes" if cert.is_expired() else "no"
    print(f"subject:          {cert.subject}")
    print(f"issuer:           {cert.issuer}")
    print(f"serial:           {cert.serial_number}")
    print(f"not valid before: {cert.not_valid_before.isoformat()}")
    print(f"not valid after:  {cert.not_valid_after.isoformat()}")
    print(f"expired:          {expired}")
    print(f"oib:              {cert.oib or '(not found in subject)'}")
    print(f"chain length:     {len(cert.chain)}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "cert" and args.cert_command == "info":
            return _cert_info(args.path)
    except FiskalizacijaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2  # pragma: no cover — unreachable while argparse enforces commands


if __name__ == "__main__":
    raise SystemExit(main())
