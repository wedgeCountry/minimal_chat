"""Start a LeanChat instance in testing mode with mock LLM and auto-login.

Usage (from the repository root):

    python scripts/run_test_working.py     # dev instance on http://127.0.0.1:8000 with mock LLM

- Starts mock LLM server first
- Then starts LeanChat on localhost (127.0.0.1:8000)
- Configures the app to use the mock LLM endpoint
- Enables auto-login (no login required, uses default test user)
- Uses a temporary data directory
- Press Ctrl+C to stop both servers
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
E2E_DIR = REPO_ROOT / "tests" / "e2e"


def find_free_port() -> int:
    """Find a free port for the mock LLM server."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(port: int, timeout: float = 15.0) -> bool:
    """Wait until a server is reachable on the given port."""
    import socket
    import urllib.request
    import urllib.error

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            # First check if port is open
            with socket.socket() as s:
                s.settimeout(1)
                s.connect(("127.0.0.1", port))

            # Port is open, try HTTP
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
                return True
            except urllib.error.HTTPError:
                # Server is responding with HTTP, even if with an error
                return True
            except Exception:
                time.sleep(0.2)
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.2)

    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a LeanChat testing instance with mock LLM and auto-login."
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
        "--mock-port",
        type=int,
        default=0,
        help="Port for mock LLM server (default: auto-select free port)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Data directory for the testing instance (default: temporary directory)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show server output for debugging",
    )
    args = parser.parse_args()

    # Set up temporary data directory
    if args.data_dir:
        data_dir = Path(args.data_dir).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
    else:
        data_dir = Path(tempfile.mkdtemp(prefix="leanchat-test-"))
        print(f"Using temporary data directory: {data_dir}", flush=True)

    # Find and set up mock LLM port
    mock_llm_port = args.mock_port if args.mock_port else find_free_port()

    # Set up environment for mock LLM server
    # Use absolute import path: tests.e2e.mock_llm:app
    mock_env = os.environ.copy()
    # Add repo root to PYTHONPATH so tests.e2e.mock_llm can be imported
    pythonpath_parts = [str(REPO_ROOT)]
    existing_path = mock_env.get("PYTHONPATH", "")
    if existing_path:
        pythonpath_parts.append(existing_path)
    mock_env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)

    # Start mock LLM server using absolute module path
    print(f"Starting mock LLM server on port {mock_llm_port}...", flush=True)
    mock_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.e2e.mock_llm:app", "--host", "127.0.0.1", "--port", str(mock_llm_port), "--log-level", "error"],
        cwd=REPO_ROOT,  # Run from repo root so tests.e2e.mock_llm can be found
        env=mock_env,
        stdout=subprocess.PIPE if not args.verbose else None,
        stderr=subprocess.PIPE if not args.verbose else None,
        text=True,
    )

    # Wait for mock LLM to be ready
    if not wait_for_server(mock_llm_port):
        print(f"Error: Mock LLM server failed to start on port {mock_llm_port}", flush=True)
        # Try to get error output
        if mock_proc.poll() is not None:
            stdout, stderr = mock_proc.communicate(timeout=1)
            print(f"Mock LLM stdout: {stdout}", flush=True)
            print(f"Mock LLM stderr: {stderr}", flush=True)
        else:
            mock_proc.terminate()
            stdout, stderr = mock_proc.communicate(timeout=5)
            print(f"Mock LLM stdout: {stdout}", flush=True)
            print(f"Mock LLM stderr: {stderr}", flush=True)
        sys.exit(1)

    print(f"Mock LLM server running on http://127.0.0.1:{mock_llm_port}/v1", flush=True)

    # Configure environment for LeanChat
    env = os.environ.copy()
    env.update({
        "LEANCHAT_DATA_DIR": str(data_dir),
        "LEANCHAT_SECRET": "test-secret",
        "LEANCHAT_API_KEY": "test-api-key",
        "LEANCHAT_LLM_BASE": f"http://127.0.0.1:{mock_llm_port}/v1",
        "LEANCHAT_HOST": args.host,
        "LEANCHAT_PORT": str(args.port),
        "LEANCHAT_AUTO_LOGIN": "1",  # Enable auto-login for testing
    })

    # Start LeanChat
    print(f"Starting LeanChat on http://{args.host}:{args.port}/...", flush=True)
    print(f"Auto-login enabled - no login required!", flush=True)
    print(f"Press Ctrl+C to stop both servers...", flush=True)

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
        # Clean up mock LLM server
        print("Stopping mock LLM server...", flush=True)
        mock_proc.terminate()
        try:
            mock_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            mock_proc.kill()
            mock_proc.wait()

        # Clean up temporary data directory
        if not args.data_dir:
            import shutil
            shutil.rmtree(data_dir, ignore_errors=True)
            print(f"Cleaned up temporary data directory: {data_dir}", flush=True)


if __name__ == "__main__":
    main()
