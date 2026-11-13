"""Start a LeanChat instance in testing mode with a real LLM and auto-login.

Usage (from the repository root):

    python scripts/run_test.py             # dev instance on http://127.0.0.1:8000 with real LLM
    python scripts/run_test.py --mockdata  # use mockdata directory with test databases

- Starts LeanChat on localhost (127.0.0.1:8000)
- Configures the app to use an LLM endpoint (default: http://127.0.0.1:1234/v1,
  override via --llm-base or LEANCHAT_E2E_LLM_BASE)
- Uses model: openai/google/gemma-4-e4b
- Enables auto-login (no login required, uses default test user)
- Uses the persistent data-test/ directory by default (data survives reruns),
  or mockdata/ with --mockdata, or a custom path with --data-dir
- Press Ctrl+C to stop the server
"""

import argparse
import os
import subprocess
import sys
from urllib.parse import urlparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
E2E_DIR = REPO_ROOT / "tests" / "e2e"


def _init_test_database(data_dir: Path) -> None:
    """Initialize the per-user test database with sample data for testing."""
    from app.auth import user_identity
    from app.db.database import Database

    print(f"Initializing test database in {data_dir}", flush=True)

    # Create directories
    users_dir = data_dir / "users"
    users_dir.mkdir(parents=True, exist_ok=True)

    # Note: We don't create the user_registry.db here - the user_registry library
    # will create it with the correct schema when init_db() is called, and the
    # auto-login flow registers the test user on first request. The per-user DB
    # identity is derived from secret + e-mail, no local users table needed.
    (data_dir / "user_registry.db").parent.mkdir(parents=True, exist_ok=True)

    db = Database(data_dir, users_dir=users_dir)

    # Use the same email that the auto-login system expects
    secret = "test-secret"
    test_email = "testuser@example.com"
    user = user_identity(secret, test_email)

    with db.user_db(user) as con:
        existing = con.execute("SELECT COUNT(*) FROM user_settings").fetchone()[0]
        if existing:
            print(f"Test data for user {test_email} already exists", flush=True)
        else:
            # Add some user settings
            con.execute(
                "INSERT INTO user_settings (key, value) VALUES (?, ?)",
                ("theme", "dark")
            )
            con.execute(
                "INSERT INTO user_settings (key, value) VALUES (?, ?)",
                ("bubbles_deletable", "true")
            )
            print(f"Initialized test data for user {test_email} (uid: {user['uid']})", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a LeanChat testing instance with real LLM and auto-login."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to (default: 8000)",
    )
    parser.add_argument(
        "--llm-base",
        default=os.environ.get("LEANCHAT_E2E_LLM_BASE", "http://127.0.0.1:1234/v1"),
        help="Base URI for the LLM endpoint (default: LEANCHAT_E2E_LLM_BASE or http://127.0.0.1:1234/v1)",
    )
    parser.add_argument(
        "--llm-model",
        default="openai/google/gemma-4-e4b",
        help="Model to use (default: openai/google/gemma-4-e4b)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Data directory for the testing instance (default: <repo>/data-test, persistent)",
    )
    parser.add_argument(
        "--mockdata",
        default=True,
        action="store_true",
        help="Use the mockdata directory for testing (creates test databases if they don't exist)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show server output for debugging",
    )
    args = parser.parse_args()

    # Set up data directory
    if args.mockdata:
        data_dir = (REPO_ROOT / "mockdata").resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        print(f"Using mockdata directory: {data_dir}", flush=True)
    elif args.data_dir:
        data_dir = Path(args.data_dir).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
    else:
        data_dir = (REPO_ROOT / "data-test").resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        print(f"Using persistent test data directory: {data_dir}", flush=True)

    # Initialize test database if using mockdata directory or if data directory is empty
    if args.mockdata or (args.data_dir and "mockdata" in str(args.data_dir)):
        _init_test_database(data_dir)
    elif not args.data_dir and not args.mockdata:
        # For temporary directories, we can also initialize test data
        _init_test_database(data_dir)

    # Use the specified real LLM endpoint
    llm_base = args.llm_base
    llm_model = args.llm_model
    parsed = urlparse(llm_base if "://" in llm_base else "http://" + llm_base)
    llm_host = parsed.hostname or "127.0.0.1"
    llm_port = str(parsed.port or "")
    print(f"Using real LLM endpoint: {llm_base} ({llm_host}:{llm_port})", flush=True)
    print(f"Using model: {llm_model}", flush=True)

    # Configure environment for LeanChat
    env = os.environ.copy()
    env.update({
        "LEANCHAT_DATA_DIR": str(data_dir),
        "LEANCHAT_REGISTRY_PATH": str(data_dir / "user_registry.db"),
        "LEANCHAT_USERS_DIR": str(data_dir / "users"),
        "LEANCHAT_SECRET": "test-secret",
        "LEANCHAT_API_KEY": "test-api-key",
        "LEANCHAT_LLM_HOST": llm_host,
        "LEANCHAT_LLM_PORT": llm_port,
        "LEANCHAT_MODEL": llm_model,
        "LEANCHAT_HOST": args.host,
        "LEANCHAT_PORT": str(args.port),
        "LEANCHAT_AUTO_LOGIN": "1",  # Enable auto-login for testing
    })

    # Start LeanChat
    print(f"Starting LeanChat on http://{args.host}:{args.port}/...", flush=True)
    print(f"Auto-login enabled - no login required!", flush=True)
    print(f"Press Ctrl+C to stop the server...", flush=True)

    try:
        # Run the main app - this will block until Ctrl+C
        subprocess.run(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", args.host, "--port", str(args.port)],
            cwd=REPO_ROOT,
            env=env,
        )
    except KeyboardInterrupt:
        print("\nShutting down...", flush=True)
    # Datenverzeichnis wird bewusst nicht aufgeraeumt: data-test/ (Default) und
    # mockdata/ bleiben erhalten, damit Daten zwischen Testlaeufen persistieren.


if __name__ == "__main__":
    main()
