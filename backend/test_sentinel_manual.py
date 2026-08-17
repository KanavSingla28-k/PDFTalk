import asyncio
import os

from starlette.requests import Request

from app.core.sentinel import guard


async def main() -> None:
    token = os.environ["SENTINEL_TEST_TOKEN"]

    # Load scripts while Redis is UP.
    await guard.load_scripts()
    print("Scripts loaded. Waiting 10 seconds...")
    print("STOP pdftalk-sentinel-redis now.")

    # Give us time to stop Redis from another terminal.
    await asyncio.sleep(10)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/documents/upload",
        "headers": [
            (b"authorization", f"Bearer {token}".encode()),
        ],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("localhost", 8000),
        "scheme": "http",
        "http_version": "1.1",
        "asgi": {
            "version": "3.0",
            "spec_version": "2.3",
        },
    }

    request = Request(scope)

    try:
        await guard.guard_for("pdftalk.documents.upload")(request)
        print("SENTINEL: ALLOWED")
        print("DECISION:", request.state.decision)

    except Exception as exc:
        print("SENTINEL: DENIED")
        print(type(exc).__name__, str(exc))


asyncio.run(main())
