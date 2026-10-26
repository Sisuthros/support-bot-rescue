"""One real call to the Meta Model API. Prints only HTTP status, model and output text, or the error message."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.client import DEFAULT_MODEL, MetaAPIError, MetaClient  # noqa: E402


def main() -> int:
    try:
        resp = MetaClient(max_calls=1).responses.create(model=DEFAULT_MODEL, input="Reply with exactly: ok")
    except MetaAPIError as e:
        print(f"status: {e.status_code}")
        print(f"error: {e.message}")
        return 1
    except Exception as e:  # network or SDK failure; the message never contains the key
        print(f"error: {type(e).__name__}: {e}")
        return 1
    print("status: 200")
    print(f"model: {resp.model}")
    print(f"output: {resp.output_text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
