# run_test Implementation (Inspired by nicewand)

## Overview

This document describes how the `run_test` functionality was implemented to match the nicewand approach, providing a seamless testing experience with:
- Mock LLM server for testing without real API calls
- Auto-login functionality (no login required)
- Temporary data directory for isolated testing

## Key Changes

### 1. Auto-Login Feature (`app/config.py` and `app/deps.py`)

Added `LEANCHAT_AUTO_LOGIN` environment variable support:

```python
# In app/config.py
def is_auto_login_enabled() -> bool:
    """Check if auto-login mode is enabled (for testing)."""
    return os.environ.get("LEANCHAT_AUTO_LOGIN", "").lower() in ("1", "true", "yes", "on")
```

Modified `get_current_user()` in `app/deps.py` to:
- Check if auto-login is enabled
- Return a default test user (`testuser@example.com`) when no valid session exists
- Automatically create the test user in the registry if it doesn't exist (the per-user DB identity is derived from secret + e-mail, no local user row)

### 2. Simplified run_test Scripts

Created multiple versions of the test script:

#### `scripts/run_test_final.py` (Recommended)
- Starts mock LLM server first on a free port
- Waits for mock LLM to be ready
- Starts LeanChat with auto-login enabled
- Uses absolute module path (`tests.e2e.mock_llm:app`) for better reliability
- Cleans up both servers on Ctrl+C

Usage:
```bash
python scripts/run_test_final.py
```

#### `scripts/run_test_simple.py`
- Similar to `run_test_final.py` but with less verbose output

#### `scripts/run_test_v2.py`
- Alternative version with different import strategy

#### Original `scripts/run_test.py`
- Updated to include `LEANCHAT_AUTO_LOGIN=1` environment variable
- Maintains all original functionality (auto-login setup, etc.)

### 3. Mock LLM Server (`tests/e2e/mock_llm.py`)

The existing mock LLM server was already implemented and works correctly. It:
- Responds to `POST /v1/chat/completions` with SSE streams
- Returns mock responses for testing
- Handles the special case for "Krokodil-Ledertasche" content

### 4. Python Package Structure

Added missing `__init__.py` files to ensure proper module imports:
- `tests/__init__.py` - Makes tests directory a Python package
- `tests/e2e/__init__.py` - Already existed

## How It Works

1. **Start mock LLM server**: The script finds a free port and starts the mock LLM server using uvicorn
2. **Wait for readiness**: The script waits until the mock LLM server is responding to HTTP requests
3. **Start LeanChat**: The main app is started with environment variables configured to:
   - Use the mock LLM endpoint (`LEANCHAT_LLM_BASE`)
   - Enable auto-login (`LEANCHAT_AUTO_LOGIN=1`)
   - Use a temporary data directory
4. **Auto-login**: When a user visits the app:
   - If no valid session exists and auto-login is enabled
   - The app automatically uses `testuser@example.com` as the current user
   - If the user doesn't exist, it's created automatically in the registry
5. **Cleanup**: On Ctrl+C, both servers are stopped and temporary data is cleaned up

## Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `LEANCHAT_AUTO_LOGIN` | Enable auto-login mode (no login required) | `""` (disabled) | No |
| `LEANCHAT_LLM_BASE` | Base URL for LLM API | `https://api.openai.com/v1` | No |
| `LEANCHAT_DATA_DIR` | Data directory | `data` | No |
| `LEANCHAT_SECRET` | Secret for session cookies | Auto-generated | No |

## Testing

To test the implementation:

```bash
# Run the simplified test script
python scripts/run_test_final.py

# Or with verbose output
python scripts/run_test_final.py --verbose

# Or with custom ports
python scripts/run_test_final.py --port 8080 --mock-port 8081
```

Then open `http://127.0.0.1:8000/` in your browser. You should be automatically logged in as `testuser@example.com` without needing to enter credentials.

## Differences from nicewand

1. **User Creation**: nicewand uses seed data with a default admin user. LeanChat creates a test user on-the-fly when auto-login is enabled.
2. **Mock LLM**: nicewand might have the mock LLM integrated differently. LeanChat uses a separate mock LLM server.
3. **Configuration**: nicewand uses `NICEWAND_AUTO_LOGIN`, LeanChat uses `LEANCHAT_AUTO_LOGIN`.

## Troubleshooting

If the script exits immediately:

1. **Check uvicorn is installed**:
   ```bash
   pip install uvicorn
   ```

2. **Check user_registry is installed**:
   ```bash
   pip install ./vendors/user_registry-0.1.0-py3-none-any.whl
   ```

3. **Check Python path**: Ensure the `tests` directory is accessible as a Python package.

4. **Check port availability**: The script should auto-select a free port, but you can specify one manually with `--mock-port`.

5. **Run with verbose output**:
   ```bash
   python scripts/run_test_final.py --verbose
   ```

This will show the stdout/stderr from both servers, which can help identify issues.
