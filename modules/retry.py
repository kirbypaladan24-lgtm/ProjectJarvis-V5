"""
JARVIS Retry Policies
================================================================
Automatic retry with exponential backoff for transient failures.
Catches network timeouts, Ollama 500s, and other recoverable errors.
"""
import os
import sys
import time
import functools
import requests

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)


# ═════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════

MAX_RETRIES = 3
INITIAL_DELAY = 1.0  # seconds
MAX_DELAY = 10.0     # seconds
BACKOFF_FACTOR = 2.0


# ═════════════════════════════════════════════════════════════
# RETRYABLE EXCEPTIONS
# ═════════════════════════════════════════════════════════════

RETRYABLE_EXCEPTIONS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)

# Retryable HTTP status codes
RETRYABLE_STATUS_CODES = {500, 502, 503, 504, 429}


# ═════════════════════════════════════════════════════════════
# DECORATOR
# ═════════════════════════════════════════════════════════════

def with_retry(max_retries=MAX_RETRIES, initial_delay=INITIAL_DELAY, backoff=BACKOFF_FACTOR):
    """
    Decorator that retries on transient failures with exponential backoff.

    Usage:
        @with_retry(max_retries=3)
        def call_ollama(prompt):
            return requests.post(...)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)

                    # Check if result is a requests.Response with retryable status
                    if isinstance(result, requests.Response):
                        if result.status_code in RETRYABLE_STATUS_CODES:
                            if attempt < max_retries:
                                print(f"[Retry]: {func.__name__} got HTTP {result.status_code}, retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
                                time.sleep(delay)
                                delay = min(delay * backoff, MAX_DELAY)
                                continue

                    return result

                except RETRYABLE_EXCEPTIONS as e:
                    last_exception = e
                    if attempt < max_retries:
                        print(f"[Retry]: {func.__name__} failed with {type(e).__name__}, retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(delay)
                        delay = min(delay * backoff, MAX_DELAY)
                    else:
                        print(f"[Retry]: {func.__name__} failed after {max_retries} retries: {e}")
                        raise

                except Exception as e:
                    # Non-retryable exception — re-raise immediately
                    raise

            # Should not reach here, but just in case
            if last_exception:
                raise last_exception
            return None

        return wrapper
    return decorator


# ═════════════════════════════════════════════════════════════
# HELPER FOR OLLAMA CALLS
# ═════════════════════════════════════════════════════════════

@with_retry(max_retries=2, initial_delay=1.0)
def call_ollama_chat(url, payload, timeout=None):
    """
    Make an Ollama /api/chat call with automatic retry.
    Returns the response JSON dict.
    """
    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


@with_retry(max_retries=2, initial_delay=1.0)
def call_ollama_generate(url, payload, timeout=None):
    """
    Make an Ollama /api/generate call with automatic retry.
    Returns the response JSON dict.
    """
    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


# ═════════════════════════════════════════════════════════════
# ERROR CLASSIFICATION
# ═════════════════════════════════════════════════════════════

def classify_error(error):
    """
    Classify an error for metrics tracking.
    Returns error code string.
    """
    if isinstance(error, requests.exceptions.Timeout):
        return "E_NETWORK_TIMEOUT"
    elif isinstance(error, requests.exceptions.ConnectionError):
        return "E_NETWORK_CONNECTION"
    elif isinstance(error, requests.exceptions.HTTPError):
        status = getattr(error.response, "status_code", 0)
        if status == 404:
            return "E_HTTP_NOT_FOUND"
        elif status == 400:
            return "E_HTTP_BAD_REQUEST"
        elif status >= 500:
            return "E_HTTP_SERVER_ERROR"
        else:
            return f"E_HTTP_{status}"
    elif isinstance(error, json.JSONDecodeError):
        return "E_JSON_PARSE"
    elif isinstance(error, ValueError):
        return "E_VALUE_ERROR"
    elif isinstance(error, KeyError):
        return "E_KEY_ERROR"
    elif isinstance(error, AttributeError):
        return "E_ATTRIBUTE_ERROR"
    elif isinstance(error, FileNotFoundError):
        return "E_FILE_NOT_FOUND"
    elif isinstance(error, PermissionError):
        return "E_PERMISSION_DENIED"
    elif isinstance(error, TimeoutError):
        return "E_TIMEOUT"
    else:
        return f"E_UNKNOWN_{type(error).__name__}"


if __name__ == "__main__":
    # Test
    print("Testing retry system...\n")

    call_count = 0

    @with_retry(max_retries=3, initial_delay=0.5)
    def flaky_function():
        global call_count
        call_count += 1
        print(f"  Attempt {call_count}")
        if call_count < 3:
            raise requests.exceptions.Timeout("Simulated timeout")
        return "Success!"

    try:
        result = flaky_function()
        print(f"\nResult: {result}")
    except Exception as e:
        print(f"\nFailed: {e}")

    # Test error classification
    print("\nTesting error classification...")
    errors = [
        requests.exceptions.Timeout("timeout"),
        requests.exceptions.ConnectionError("conn error"),
        ValueError("bad value"),
        KeyError("missing key"),
        FileNotFoundError("no file"),
    ]
    for e in errors:
        code = classify_error(e)
        print(f"  {type(e).__name__}: {code}")
