"""Start a LeanChat instance in testing mode with a real LLM and auto-login.

Usage (from the repository root):

    python scripts/run_test.py             # dev instance on http://127.0.0.1:8000 with real LLM
    python scripts/run_test.py --mockdata  # use mockdata directory with test databases

- Starts LeanChat on localhost (127.0.0.1:8000)
- Configures the app to use a real LLM endpoint at http://100.100.180.90:1234/v1
- Uses model: openai/google/gemma-4-e4b
- Enables auto-login (no login required, uses default test user)
- Uses a temporary data directory by default, or mockdata/ with --mockdata
- Press Ctrl+C to stop the server
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
E2E_DIR = REPO_ROOT / "tests" / "e2e"


def _init_test_database(data_dir: Path) -> None:
    """Initialize test databases with sample data for testing."""
    from app.db import crypto
    from app.db.database import Database
    
    print(f"Initializing test database in {data_dir}", flush=True)
    
    # Create directories
    users_dir = data_dir / "users"
    users_dir.mkdir(parents=True, exist_ok=True)
    
    # Configuration
    secret = "test-secret"
    registry_path = data_dir / "user_registry.db"
    
    # Note: We don't create the user_registry.db here - the user_registry library
    # will create it with the correct schema when init_db() is called
    # Just make sure the parent directory exists
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create local users database
    db = Database(data_dir, secret, users_dir=users_dir)
    
    # Use the same email that the auto-login system expects
    test_email = "testuser@example.com"
    test_uid = "testuser-123"
    
    existing = db.get_user_by_email(test_email)
    if not existing:
        user_key = crypto.new_key()
        user = db.create_local_user(test_uid, test_email, user_key)
        print(f"Created local user: {test_email} with uid: {test_uid}", flush=True)
        
        # Initialize the user's database with some test data
        with db.user_db(user) as con:
            # Create a test session
            session_id = "test-session-1"
            con.execute(
                "INSERT INTO sessions (id, name, ts) VALUES (?, ?, ?)",
                (session_id, "Test Session", 1234567890)
            )
            
            # Add some test messages
            con.execute(
                "INSERT INTO messages (session_id, role, type, text, in_context, attachments, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, "user", "message", "Hello, this is a test message", 1, "[]", 1234567890)
            )
            con.execute(
                "INSERT INTO messages (session_id, role, type, text, in_context, attachments, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, "assistant", "message", "This is a test response from the assistant", 1, "[]", 1234567891)
            )
            
            # Add some user settings
            con.execute(
                "INSERT INTO user_settings (key, value) VALUES (?, ?)",
                ("theme", "dark")
            )
            con.execute(
                "INSERT INTO user_settings (key, value) VALUES (?, ?)", 
                ("bubbles_deletable", "true")
            )
            
            print(f"Initialized test data for user {test_email}", flush=True)
    else:
        print(f"Local user {test_email} already exists", flush=True)


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
        default="http://100.100.180.90:1234/v1",
        help="Base URI for the LLM endpoint (default: http://100.100.180.90:1234/v1)",
    )
    parser.add_argument(
        "--llm-model",
        default="openai/google/gemma-4-e4b",
        help="Model to use (default: openai/google/gemma-4-e4b)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Data directory for the testing instance (default: temporary directory)",
    )
    parser.add_argument(
        "--mockdata",
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
        data_dir = Path(tempfile.mkdtemp(prefix="leanchat-test-"))
        print(f"Using temporary data directory: {data_dir}", flush=True)

    # Initialize test database if using mockdata directory or if data directory is empty
    if args.mockdata or (args.data_dir and "mockdata" in str(args.data_dir)):
        _init_test_database(data_dir)
    elif not args.data_dir and not args.mockdata:
        # For temporary directories, we can also initialize test data
        _init_test_database(data_dir)

    # Use the specified real LLM endpoint
    llm_base = args.llm_base
    llm_model = args.llm_model
    print(f"Using real LLM endpoint: {llm_base}", flush=True)
    print(f"Using model: {llm_model}", flush=True)

    # Configure environment for LeanChat
    env = os.environ.copy()
    env.update({
        "LEANCHAT_DATA_DIR": str(data_dir),
        "LEANCHAT_REGISTRY_PATH": str(data_dir / "user_registry.db"),
        "LEANCHAT_USERS_DIR": str(data_dir / "users"),
        "LEANCHAT_SECRET": "test-secret",
        "LEANCHAT_API_KEY": "test-api-key",
        "LEANCHAT_LLM_BASE": llm_base,
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
    finally:
        # Clean up temporary data directory (but not mockdata or explicitly specified directories)
        if not args.data_dir and not args.mockdata:
            import shutil
            shutil.rmtree(data_dir, ignore_errors=True)
            print(f"Cleaned up temporary data directory: {data_dir}", flush=True)


if __name__ == "__main__":
    main()
