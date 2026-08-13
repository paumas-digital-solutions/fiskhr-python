"""The ``fiskalhr`` command-line interface.

Commands: ``cert info``, ``zki``, ``echo``. ``validate`` and ``fiscalize``
arrive with the corresponding library phases.

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
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fiskalhr import __version__
from fiskalhr.core.certs import Certificate
from fiskalhr.core.environment import Environment
from fiskalhr.core.errors import FiskalizacijaError
from fiskalhr.core.signing import SignatureMethod

PASSWORD_ENV_VAR = "FISKALHR_P12_PASSWORD"

_ZKI_DATETIME_CLI_FORMAT = "%d.%m.%Y %H:%M:%S"


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

    zki_parser = subparsers.add_parser(
        "zki",
        help="compute a ZKI offline",
        description=(
            "Compute the zastitni kod izdavatelja for a receipt, fully offline. "
            f"The P12 password is taken from ${PASSWORD_ENV_VAR} or prompted."
        ),
    )
    zki_parser.add_argument("cert", help="path to the .p12/.pfx file")
    zki_parser.add_argument("--oib", required=True, help="issuer OIB (11 digits)")
    zki_parser.add_argument(
        "--datum-vrijeme",
        required=True,
        metavar="'dd.MM.yyyy HH:MM:SS'",
        help="receipt issue date and time, local Croatian time",
    )
    zki_parser.add_argument("--br-ozn-rac", required=True, help="receipt number (brOznRac)")
    zki_parser.add_argument("--ozn-pos-pr", required=True, help="business premises (oznPosPr)")
    zki_parser.add_argument("--ozn-nap-ur", required=True, help="payment device (oznNapUr)")
    zki_parser.add_argument("--iznos", required=True, help="total amount, e.g. 125.00")
    zki_parser.add_argument(
        "--legacy-sha1",
        action="store_true",
        help="use the legacy RSA-SHA1 method (production transition period only)",
    )

    echo_parser = subparsers.add_parser(
        "echo",
        help="call the CIS echo method (connectivity test)",
        description="Send an EchoRequest to the CIS service and print the reply.",
    )
    echo_parser.add_argument("text", nargs="?", default="fiskalhr echo", help="text to echo")
    echo_parser.add_argument(
        "--env",
        choices=[env.value for env in Environment],
        default=Environment.DEMO.value,
        help="target environment (default: demo)",
    )

    validate_parser = subparsers.add_parser(
        "validate",
        help="validate an eRacun (UBL Invoice/CreditNote) against HR CIUS 2025",
        description=(
            "Validate a UBL 2.1 eRacun: XSD structure, then the HR CIUS 2025 "
            "Schematron rules (requires the fiskalhr[validation] extra)."
        ),
    )
    validate_parser.add_argument("path", help="path to the eRacun XML file")
    validate_parser.add_argument(
        "--no-schematron",
        action="store_true",
        help="XSD-only validation (skip the HR CIUS business rules)",
    )

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


def _zki(args: argparse.Namespace) -> int:
    from fiskalhr.f1.zki import izracunaj_zki

    try:
        datum_vrijeme = datetime.strptime(args.datum_vrijeme, _ZKI_DATETIME_CLI_FORMAT)
    except ValueError:
        print(
            f"error: --datum-vrijeme must match 'dd.MM.yyyy HH:MM:SS', got {args.datum_vrijeme!r}",
            file=sys.stderr,
        )
        return 2
    try:
        iznos = Decimal(args.iznos)
    except InvalidOperation:
        print(f"error: --iznos is not a valid amount: {args.iznos!r}", file=sys.stderr)
        return 2

    cert = Certificate.from_p12(args.cert, _read_password())
    zki = izracunaj_zki(
        cert.private_key,
        oib=args.oib,
        datum_vrijeme=datum_vrijeme,
        br_ozn_rac=args.br_ozn_rac,
        ozn_pos_pr=args.ozn_pos_pr,
        ozn_nap_ur=args.ozn_nap_ur,
        ukupan_iznos=iznos,
        method=SignatureMethod.RSA_SHA1 if args.legacy_sha1 else SignatureMethod.RSA_SHA256,
    )
    print(zki)
    return 0


def _echo(args: argparse.Namespace) -> int:
    from fiskalhr.core.transport import SoapClient
    from fiskalhr.f1.client import _SOAP_ACTION_BASE
    from fiskalhr.f1.messages import build_echo_request, parse_echo_response
    from fiskalhr.f1.service import SERVICE_URLS

    env = Environment(args.env)
    with SoapClient(SERVICE_URLS[env]) as soap:
        response = soap.call(build_echo_request(args.text), soap_action=f"{_SOAP_ACTION_BASE}/echo")
    print(parse_echo_response(response))
    return 0


def _validate(args: argparse.Namespace) -> int:
    from pathlib import Path

    from fiskalhr.f2.validation import validate

    report = validate(Path(args.path).read_bytes(), schematron=not args.no_schematron)
    for finding in report.findings:
        rule = f" [{finding.rule}]" if finding.rule else ""
        location = f" @ {finding.location}" if finding.location else ""
        print(f"{finding.severity.value}{rule}: {finding.message}{location}")

    checked = "XSD + Schematron" if report.schematron_ran else "XSD"
    if report.ok:
        print(f"OK ({checked}; {len(report.warnings)} warning(s))")
        return 0
    print(f"INVALID ({checked}; {len(report.errors)} error(s))", file=sys.stderr)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "cert" and args.cert_command == "info":
            return _cert_info(args.path)
        if args.command == "zki":
            return _zki(args)
        if args.command == "echo":
            return _echo(args)
        if args.command == "validate":
            return _validate(args)
    except FiskalizacijaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2  # pragma: no cover — unreachable while argparse enforces commands


if __name__ == "__main__":
    raise SystemExit(main())
