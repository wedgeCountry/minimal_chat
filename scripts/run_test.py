"""Start a LeanChat instance in testing mode with mock LLM and auto-login.

Usage (from the repository root):

    python scripts/run_test.py     # dev instance on http://127.0.0.1:8000 with mock LLM

- Starts LeanChat on localhost (127.0.0.1:8000)
- Uses a temporary data directory with mock data
- Starts the mock LLM server from tests/e2e/mock_llm.py
- Configures the app to use the mock LLM endpoint
- Auto-creates a test user and modifies index.html for auto-login
- When you open the URL, you'll be automatically logged in
"""

import argparse
import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# Check if uvicorn is available
try:
    import uvicorn
    _UVICORN_AVAILABLE = True
except ImportError:
    _UVICORN_AVAILABLE = False

REPO_ROOT = Path(__file__).resolve().parent.parent
E2E_DIR = REPO_ROOT / "tests" / "e2e"

# Global state for cleanup
_auto_login_setup = None


def _free_port() -> int:
    """Find a free port for the mock LLM server."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 15.0, path: str = "/") -> None:
    """Wait until a server is reachable on the given port and path."""
    import urllib.error
    import urllib.request
    import socket

    deadline = time.time() + timeout
    last_error = None
    
    while time.time() < deadline:
        try:
            # First check if port is open
            with socket.socket() as s:
                s.settimeout(1)
                s.connect(("127.0.0.1", port))
            
            # Port is open, try HTTP
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=1)
                return
            except urllib.error.HTTPError as e:
                # Server is responding with HTTP, even if with an error
                return
            except Exception as e:
                last_error = e
                time.sleep(0.2)
        except (ConnectionRefusedError, socket.timeout, OSError) as e:
            last_error = e
            time.sleep(0.2)
    
    raise RuntimeError(f"Server on port {port} not reachable after {timeout} seconds. Last error: {last_error}")


def start_mock_llm(port: int) -> subprocess.Popen:
    """Start the mock LLM server and return the process."""
    print(f"Starting mock LLM server on port {port}...", flush=True)
    
    # Ensure the e2e directory is in the Python path
    env = os.environ.copy()
    # Add both the e2e directory and the repo root to PYTHONPATH
    python_path_parts = [str(E2E_DIR), str(REPO_ROOT)]
    existing_path = env.get("PYTHONPATH", "")
    if existing_path:
        python_path_parts.append(existing_path)
    env["PYTHONPATH"] = os.pathsep.join(python_path_parts)
    
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "mock_llm:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
        cwd=E2E_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    
    return proc


def cleanup_auto_login():
    """Restore original index.html if we modified it."""
    global _auto_login_setup
    if _auto_login_setup and not _auto_login_setup.get('restored', False):
        try:
            if _auto_login_setup['backup_index'].exists():
                shutil.copy2(_auto_login_setup['backup_index'], _auto_login_setup['original_index'])
                _auto_login_setup['backup_index'].unlink()
                _auto_login_setup['restored'] = True
                print(f"Restored original index.html", flush=True)
        except Exception as e:
            print(f"Warning: Could not restore index.html: {e}", flush=True)


def signal_handler(sig, frame):
    """Handle interrupt signals to ensure cleanup."""
    print("\nInterrupted, cleaning up...", flush=True)
    cleanup_auto_login()
    sys.exit(0)


def main() -> None:
    global _auto_login_setup
    # Set up signal handler for cleanup
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    if not _UVICORN_AVAILABLE:
        print("Error: uvicorn is not installed. Please install it with:", flush=True)
        print("  pip install uvicorn", flush=True)
        sys.exit(1)
    
    parser = argparse.ArgumentParser(
        description="Run a LeanChat testing instance with mock LLM."
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

    # Start mock LLM server
    mock_llm_port = _free_port()
    mock_llm_proc = start_mock_llm(mock_llm_port)
    
    try:
        # Wait for mock LLM to be ready - check root path first
        try:
            _wait_for_server(mock_llm_port, path="/")
            print(f"Mock LLM server running on http://127.0.0.1:{mock_llm_port}/v1", flush=True)
        except RuntimeError as e:
            # Try to get error output from the mock LLM process
            if mock_llm_proc.poll() is not None:
                stdout, stderr = mock_llm_proc.communicate(timeout=1)
                print(f"Mock LLM stdout: {stdout}", flush=True)
                print(f"Mock LLM stderr: {stderr}", flush=True)
            else:
                # Process is still running, try to check if it's listening
                import socket
                try:
                    with socket.socket() as s:
                        s.settimeout(1)
                        s.connect(("127.0.0.1", mock_llm_port))
                    print(f"Port {mock_llm_port} is open but not responding to HTTP", flush=True)
                except Exception as connect_error:
                    print(f"Port {mock_llm_port} connection error: {connect_error}", flush=True)
            raise
        
        # Configure environment for LeanChat
        env = dict(os.environ)
        env.update({
            "LEANCHAT_DATA_DIR": str(data_dir),
            "LEANCHAT_SECRET": "test-secret",
            "LEANCHAT_API_KEY": "test-api-key",
            "LEANCHAT_LLM_BASE": f"http://127.0.0.1:{mock_llm_port}/v1",
            "LEANCHAT_HOST": args.host,
            "LEANCHAT_PORT": str(args.port),
        })
        
        # Start LeanChat
        print(f"Starting LeanChat on http://{args.host}:{args.port}/...", flush=True)
        app_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", args.host, "--port", str(args.port)],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE if not args.verbose else None,
            stderr=subprocess.PIPE if not args.verbose else None,
            text=True,
        )
        
        try:
            _wait_for_server(args.port)
            print(f"LeanChat running on http://{args.host}:{args.port}/", flush=True)
            
            # Auto-create a test user and set up auto-login
            print("Creating test user and setting up auto-login...", flush=True)
            test_username = "testuser"
            test_password = "testpass123"
            
            # Prepare the registration request
            register_data = json.dumps({
                "username": test_username,
                "password": test_password,
                "key": "test-key-12345678901234567890123456789012"  # 32-byte key for encryption
            }).encode("utf-8")
            
            register_req = urllib.request.Request(
                f"http://{args.host}:{args.port}/api/auth/register",
                data=register_data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            
            test_token = ""
            try:
                with urllib.request.urlopen(register_req, timeout=10) as response:
                    result = json.loads(response.read().decode("utf-8"))
                    test_token = result.get("token", "")
                    
                    if test_token:
                        # Create a temporary index.html with auto-login
                        try:
                            static_dir = REPO_ROOT / "static"
                            original_index = static_dir / "index.html"
                            temp_index = data_dir / "index.html"
                            
                            # Read original index.html
                            original_content = original_index.read_text(encoding="utf-8")
                            
                            # Insert auto-login script before the main script
                            auto_login_script = f"""<script>
// Auto-login for test mode
sessionStorage.setItem('leanchat.token', '{test_token}');
</script>"""
                            
                            # Find the position to insert (before the main script tag)
                            main_script_pos = original_content.find('<script type="module" src="/js/main.js"></script>')
                            if main_script_pos != -1:
                                modified_content = original_content[:main_script_pos] + auto_login_script + original_content[main_script_pos:]
                            else:
                                # Fallback: insert before closing body tag
                                body_close_pos = original_content.find('</body>')
                                if body_close_pos != -1:
                                    modified_content = original_content[:body_close_pos] + auto_login_script + original_content[body_close_pos:]
                                else:
                                    modified_content = original_content + auto_login_script
                            
                            # Write the modified index.html to the data directory
                            temp_index.parent.mkdir(parents=True, exist_ok=True)
                            temp_index.write_text(modified_content, encoding="utf-8")
                            
                            # Update the static files directory to serve from our temp directory
                            # We'll do this by copying the modified file to the static directory temporarily
                            backup_index = static_dir / "index.html.bak"
                            if not backup_index.exists():
                                shutil.copy2(original_index, backup_index)
                            shutil.copy2(temp_index, original_index)
                            
                            print(f"\nAuto-login configured!", flush=True)
                            print(f"  Username: {test_username}", flush=True)
                            print(f"  Password: {test_password}", flush=True)
                            print(f"  Token:    {test_token[:20]}...", flush=True)
                            print(f"\nOpen http://{args.host}:{args.port}/ to start using LeanChat (you'll be auto-logged in)", flush=True)
                            
                            # Store info for cleanup
                            _auto_login_setup = {
                                "original_index": original_index,
                                "backup_index": backup_index,
                                "temp_index": temp_index,
                                "restored": False
                            }
                        except Exception as e:
                            print(f"Warning: Could not set up auto-login: {e}", flush=True)
                            print(f"You will need to log in manually at http://{args.host}:{args.port}/", flush=True)
                            print(f"  Username: {test_username}", flush=True)
                            print(f"  Password: {test_password}", flush=True)
                    else:
                        print(f"Warning: No token received from registration", flush=True)
                        print(f"You will need to register manually at http://{args.host}:{args.port}/", flush=True)
                        
            except urllib.error.HTTPError as e:
                print(f"Warning: Could not create test user (HTTP {e.code}): {e.reason}", flush=True)
                print(f"You will need to register manually at http://{args.host}:{args.port}/", flush=True)
            except Exception as e:
                print(f"Warning: Could not create test user: {e}", flush=True)
                print(f"You will need to register manually at http://{args.host}:{args.port}/", flush=True)
            
            print("\nPress Ctrl+C to stop both servers...", flush=True)
            
            # Wait for user to stop
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nShutting down...", flush=True)
        finally:
            # Restore original index.html if we modified it
            cleanup_auto_login()
            _auto_login_setup = None
            
            app_proc.terminate()
            try:
                app_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                app_proc.kill()
                app_proc.wait()
    finally:
        mock_llm_proc.terminate()
        try:
            mock_llm_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            mock_llm_proc.kill()
            mock_llm_proc.wait()
        
        # Clean up temporary data directory
        if not args.data_dir:
            shutil.rmtree(data_dir, ignore_errors=True)
            print(f"Cleaned up temporary data directory: {data_dir}", flush=True)


if __name__ == "__main__":
    main()
