"""Administrative CLI for API-key provisioning.

There is no public API endpoint for issuing keys — this is the only
way one is ever created. Run using the existing application image, no
host-native Python install required:

    docker compose -f compose.prod.yml run --rm api \\
        python -m app.auth.manage_api_keys issue-student --account-number 423090349

    python -m app.auth.manage_api_keys issue-admin --label "Ulises"
    python -m app.auth.manage_api_keys revoke --id 3
    python -m app.auth.manage_api_keys rotate-student --account-number 423090349
    python -m app.auth.manage_api_keys list

A plaintext key is printed exactly once, at issue/rotate time, to
stdout only — never logged, never stored. `list` never prints a
plaintext key or the full key_hash.
"""

import argparse
import sys

from app.auth.api_keys import (
    ActiveStudentKeyExistsError,
    GeneratedKey,
    StudentNotFoundError,
    issue_admin_key,
    issue_student_key,
    list_keys,
    revoke_key,
    rotate_student_key,
)
from app.db.session import SessionLocal


def _print_issued(action: str, generated: GeneratedKey) -> None:
    print(f"{action} (id={generated.id}, prefix={generated.key_prefix})")
    print(generated.plaintext)
    print("Store this key now — it cannot be recovered. Rotate/reissue if it's lost.")


def _issue_student(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        try:
            generated = issue_student_key(
                db, account_number=args.account_number, label=args.label
            )
        except StudentNotFoundError:
            print(f"No student found with account_number={args.account_number!r}", file=sys.stderr)
            return 1
        except ActiveStudentKeyExistsError:
            print(
                "Student already has an active key — use rotate-student to replace it.",
                file=sys.stderr,
            )
            return 1
    _print_issued("issued student key", generated)
    return 0


def _issue_admin(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        generated = issue_admin_key(db, label=args.label)
    _print_issued("issued admin key", generated)
    return 0


def _revoke(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        revoke_key(db, api_key_id=args.id)
    print(f"revoked key id={args.id}")
    return 0


def _rotate_student(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        try:
            generated = rotate_student_key(
                db, account_number=args.account_number, label=args.label
            )
        except StudentNotFoundError:
            print(f"No student found with account_number={args.account_number!r}", file=sys.stderr)
            return 1
    _print_issued("rotated student key", generated)
    return 0


def _list(_args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        summaries = list_keys(db)
    for summary in summaries:
        target = summary.account_number or summary.label or "-"
        state = "revoked" if summary.revoked_at is not None else "active"
        print(
            f"id={summary.id}\tprefix={summary.key_prefix}\trole={summary.role}\t"
            f"target={target}\tstatus={state}\tcreated_at={summary.created_at.isoformat()}"
        )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.auth.manage_api_keys")
    subparsers = parser.add_subparsers(dest="command", required=True)

    issue_student = subparsers.add_parser("issue-student", help="Issue a new student API key")
    issue_student.add_argument("--account-number", required=True)
    issue_student.add_argument("--label", default=None)

    issue_admin = subparsers.add_parser("issue-admin", help="Issue a new admin API key")
    issue_admin.add_argument("--label", default=None)

    revoke = subparsers.add_parser("revoke", help="Revoke an API key by id")
    revoke.add_argument("--id", type=int, required=True)

    rotate_student = subparsers.add_parser(
        "rotate-student", help="Revoke a student's active key(s) and issue a new one"
    )
    rotate_student.add_argument("--account-number", required=True)
    rotate_student.add_argument("--label", default=None)

    subparsers.add_parser("list", help="List API key metadata (never plaintext or full hash)")

    return parser


def main() -> int:
    args = _build_parser().parse_args()

    if args.command == "issue-student":
        return _issue_student(args)
    if args.command == "issue-admin":
        return _issue_admin(args)
    if args.command == "revoke":
        return _revoke(args)
    if args.command == "rotate-student":
        return _rotate_student(args)
    if args.command == "list":
        return _list(args)
    raise AssertionError(f"unhandled command: {args.command!r}")  # argparse guarantees a match


if __name__ == "__main__":
    raise SystemExit(main())
