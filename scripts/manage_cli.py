#!/usr/bin/env python3
"""CLI for managing LeanChat users: invite and reset commands.

Usage:
    python scripts/manage_cli.py invite <email> [--expires-days N] [--db PATH] [--base-url URL]
    python scripts/manage_cli.py reset <email> [--expires-days N] [--db PATH] [--base-url URL]

Commands:
    invite  Create a single-use invitation link for user registration
    reset   Create a single-use password reset link

Options:
    --email, -e         E-mail address of the user (mandatory)
    --expires-days, -d  Link validity in days (default: 7)
    --db, -db           Path to user registry database (default: data/user_registry.db)
    --base-url, -u      Base URL for generated links (default: http://127.0.0.1:8000)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import load_config
from user_registry import UserRegistry

# Defaults matching the existing scripts
DEFAULT_EXPIRES_DAYS = 7
DEFAULT_BASE_URL = "http://127.0.0.1:8000"

CONFIG = load_config()

def get_default_db_path() -> Path:
    """Determine the default database path from environment or fallback."""
    import os

    # Check environment variable first (matches app/config.py)
    registry_path = CONFIG.registry_path
    return Path(registry_path).resolve()


def create_invite_link(
    email: str,
    db_path: Path,
    expires_in_days: int,
    base_url: str,
) -> str:
    """Create a single-use invitation link."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    registry = UserRegistry(str(db_path))
    registry.init_db()

    try:
        token = registry.create_invitation(
            email, expires_in_seconds=expires_in_days * 24 * 3600
        )
    finally:
        registry.close()

    return f"{base_url.rstrip('/')}/auth/register?invite={token}"


def create_reset_link(
    email: str,
    db_path: Path,
    expires_in_days: int,
    base_url: str,
) -> str:
    """Create a single-use password reset link."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    registry = UserRegistry(str(db_path))
    registry.init_db()

    try:
        token = registry.create_password_reset(
            email, expires_in_seconds=expires_in_days * 24 * 3600
        )
    finally:
        registry.close()

    return f"{base_url.rstrip('/')}/auth/reset-password?token={token}"


def cmd_invite(args: argparse.Namespace) -> int:
    """Handle the 'invite' command."""
    db_path = args.db or get_default_db_path()
    link = create_invite_link(
        email=args.email,
        db_path=db_path,
        expires_in_days=args.expires_days,
        base_url=args.base_url,
    )
    print(f"Invitation link (single-use, bound to {args.email}):")
    print(f"  {link}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    """Handle the 'reset' command."""
    db_path = args.db or get_default_db_path()
    link = create_reset_link(
        email=args.email,
        db_path=db_path,
        expires_in_days=args.expires_days,
        base_url=args.base_url,
    )
    print(f"Password reset link (single-use, bound to {args.email}):")
    print(f"  {link}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="manage_cli",
        description="CLI for managing LeanChat users (invite and password reset).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Invite command
    invite_parser = subparsers.add_parser(
        "invite",
        help="Create a single-use invitation link for user registration",
    )
    invite_parser.add_argument(
        "-e", "--email",
        required=True,
        help="E-mail address for the invitation (mandatory)",
    )
    invite_parser.add_argument(
        "-d", "--expires-days",
        type=int,
        default=DEFAULT_EXPIRES_DAYS,
        help=f"Link validity in days (default: {DEFAULT_EXPIRES_DAYS})",
    )
    invite_parser.add_argument(
        "-db", "--db",
        type=Path,
        default=None,
        help=f"Path to user registry database (default: {get_default_db_path()})",
    )
    invite_parser.add_argument(
        "-u", "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL for generated links (default: {DEFAULT_BASE_URL})",
    )
    invite_parser.set_defaults(func=cmd_invite)

    # Reset command
    reset_parser = subparsers.add_parser(
        "reset",
        help="Create a single-use password reset link",
    )
    reset_parser.add_argument(
        "-e", "--email",
        required=True,
        help="E-mail address for the password reset (mandatory)",
    )
    reset_parser.add_argument(
        "-d", "--expires-days",
        type=int,
        default=DEFAULT_EXPIRES_DAYS,
        help=f"Link validity in days (default: {DEFAULT_EXPIRES_DAYS})",
    )
    reset_parser.add_argument(
        "-db", "--db",
        type=Path,
        default=None,
        help=f"Path to user registry database (default: {get_default_db_path()})",
    )
    reset_parser.add_argument(
        "-u", "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL for generated links (default: {DEFAULT_BASE_URL})",
    )
    reset_parser.set_defaults(func=cmd_reset)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
