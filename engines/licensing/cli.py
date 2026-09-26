"""The vendor's licensing tool (`P7.1`).

    t2pbi-license keygen  --out ~/dashboardbridge-keys
    t2pbi-license issue   --key ~/dashboardbridge-keys/vendor-private.pem \\
                          --customer "Northwind BI" --days 365 \\
                          --features convert --seats 5 --out northwind.lic
    t2pbi-license inspect --file northwind.lic \\
                          --public-key ~/dashboardbridge-keys/vendor-public.pem

The engine could already mint and check a licence and nothing could run it, so
issuing one was a Python session - and a step that has to be improvised is a
step that gets improvised differently each time. This is the vendor side and
only the vendor side: a deployment holds the public half and has no way to sign
anything.

## Why this refuses to write where it is told

The private key ends the scheme for every customer at once if it leaks.
`tests/test_licensing.py` fails the build when one is committed, which is the
last line of defence rather than the first: it notices after the mistake, and
only if the suite runs before the push.

So `keygen` will not create a private key anywhere inside a git work tree, and
`issue` will not write a customer's licence there either. A tool that cannot put
the key in the repository is a better guarantee than a test that finds it
afterwards, and the cost is one line of an operator's attention instead of a
revocation and a re-issue to everyone.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from engines.licensing import (
    LicenseError,
    LicenseExpired,
    LicenseInvalid,
    generate_keypair,
    issue,
    verify,
)

PRIVATE_NAME = "vendor-private.pem"
PUBLIC_NAME = "vendor-public.pem"


class Refused(Exception):
    """Something the operator asked for that this will not do.

    Separate from `LicenseError` so the two reach the same exit path with
    different sentences: one is "that licence is wrong", the other is "that
    place is wrong".
    """


def _inside_a_work_tree(path: Path) -> Path | None:
    """The git work tree `path` is in, if any.

    Checked by walking up for a `.git` entry rather than by running `git`: this
    has to work on a vendor's laptop with no git on `PATH`, and a wrong answer
    in the permissive direction is the one that writes a private key into a
    repository.
    """
    for candidate in [path, *path.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _refuse_if_committable(path: Path, what: str) -> None:
    tree = _inside_a_work_tree(path)
    if tree is not None:
        raise Refused(
            f"{path} is inside the git work tree at {tree}, and a {what} does "
            "not belong in a repository. Write it somewhere outside version "
            "control - a password manager, a key vault, or a directory you "
            "back up deliberately."
        )


def _keygen(args: argparse.Namespace) -> int:
    out = Path(args.out).expanduser().resolve()
    _refuse_if_committable(out, "private key")

    private_path, public_path = out / PRIVATE_NAME, out / PUBLIC_NAME
    if private_path.exists() or public_path.exists():
        raise Refused(
            f"{out} already holds a vendor keypair. Overwriting it does not "
            "lose one licence - it orphans every licence ever issued, because "
            "none of them verify against a new public half. Move the old pair "
            "aside deliberately if that is really what you want."
        )

    private_pem, public_pem = generate_keypair()
    out.mkdir(parents=True, exist_ok=True)
    private_path.write_text(private_pem, encoding="utf-8")
    public_path.write_text(public_pem, encoding="utf-8")
    try:
        private_path.chmod(0o600)
    except OSError:
        # Windows ACLs do not follow POSIX modes. Not fatal, and not silent.
        print(
            f"note: could not restrict permissions on {private_path}; check "
            "that only you can read it.",
            file=sys.stderr,
        )

    # The private half is named, never printed. A key in a terminal is a key in
    # a scrollback buffer and in whatever records that session.
    print(f"private key: {private_path}  (never commit, never send)")
    print(f"public key:  {public_path}")
    print()
    print("Ship the public key with the application:")
    print(f"    LICENSE_PUBLIC_KEY=\"$(cat {public_path})\"")
    return 0


def _issue(args: argparse.Namespace) -> int:
    out = Path(args.out).expanduser().resolve()
    _refuse_if_committable(out, "customer licence")

    issued = date.fromisoformat(args.issued) if args.issued else date.today()
    if args.expires:
        expires = date.fromisoformat(args.expires)
    elif args.days is not None:
        expires = issued + timedelta(days=args.days)
    else:
        raise Refused("Give either --days or --expires; a licence needs an end.")

    features = [part.strip() for part in args.features.split(",") if part.strip()]
    if not features:
        raise Refused(
            "A licence with no features buys nothing. Pass --features convert "
            "for the usual one."
        )

    token = issue(
        private_key=Path(args.key).expanduser().read_text(encoding="utf-8"),
        customer=args.customer,
        issued=issued,
        expires=expires,
        features=features,
        seats=args.seats,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(token + "\n", encoding="utf-8")

    print(f"licence: {out}")
    print(f"  customer: {args.customer}")
    print(f"  valid:    {issued} to {expires} ({(expires - issued).days} days)")
    print(f"  features: {', '.join(sorted(features))}   seats: {args.seats}")
    print()
    print("The customer installs it by pointing the deployment at the file:")
    print("    LICENSE_FILE=/path/to/licence")
    return 0


def _inspect(args: argparse.Namespace) -> int:
    token = (
        Path(args.file).expanduser().read_text(encoding="utf-8").strip()
        if args.file
        else str(args.token or "").strip()
    )
    if not token:
        raise Refused("Give --file or a token to inspect.")

    licence = verify(
        token,
        public_key=Path(args.public_key).expanduser().read_text(encoding="utf-8"),
        today=date.today(),
    )
    print(
        json.dumps(
            {
                "customer": licence.customer,
                "issued": str(licence.issued),
                "expires": str(licence.expires),
                "days_remaining": licence.days_remaining(date.today()),
                "features": sorted(licence.features),
                "seats": licence.seats,
            },
            indent=2,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="t2pbi-license",
        description="Mint and check DashboardBridge licences (vendor side).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    keygen = commands.add_parser("keygen", help="create the vendor keypair (once)")
    keygen.add_argument("--out", required=True, help="a directory outside any repository")
    keygen.set_defaults(handler=_keygen)

    mint = commands.add_parser("issue", help="mint a licence for one customer")
    mint.add_argument("--key", required=True, help="path to vendor-private.pem")
    mint.add_argument("--customer", required=True)
    mint.add_argument("--days", type=int, help="length from the issue date")
    mint.add_argument("--expires", help="ISO date, instead of --days")
    mint.add_argument("--issued", help="ISO date; defaults to today")
    mint.add_argument(
        "--features",
        default="convert",
        help=(
            "comma separated. 'convert' (and 'ai') as before; add engine features to sell "
            "engines separately: tableau, microstrategy, qlik. A licence naming no engine "
            "feature covers every installed engine."
        ),
    )
    mint.add_argument("--seats", type=int, default=1)
    mint.add_argument("--out", required=True)
    mint.set_defaults(handler=_issue)

    look = commands.add_parser("inspect", help="read a licence and check its signature")
    look.add_argument("--file")
    look.add_argument("--token")
    look.add_argument("--public-key", required=True, dest="public_key")
    look.set_defaults(handler=_inspect)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.handler(args)
    except Refused as refusal:
        print(str(refusal), file=sys.stderr)
        return 2
    except LicenseExpired as expired:
        # Reported, and reported *as expired* - an operator inspecting a lapsed
        # licence is having exactly the conversation the dates answer, so the
        # message carries them rather than saying only "invalid".
        print(str(expired), file=sys.stderr)
        return 3
    except LicenseInvalid as invalid:
        print(str(invalid), file=sys.stderr)
        return 4
    except LicenseError as error:
        print(str(error), file=sys.stderr)
        return 4
    except OSError as error:
        print(f"could not read or write a file: {error}", file=sys.stderr)
        return 5


if __name__ == "__main__":  # pragma: no cover - the module entry point
    raise SystemExit(main())
