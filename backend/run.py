import os

import uvicorn

from app.main import app as fastapi_app
from app.parent_watch import start_parent_watch

# On SIGTERM, wait at most this long for in-flight requests. Without a limit a long preview
# analysis keeps the process (and its CPU use) alive after the app has quit.
GRACEFUL_SHUTDOWN_SEC = 3


def main() -> None:
    host = os.getenv("DRUMSHEET_HOST", "127.0.0.1")
    port = int(os.getenv("DRUMSHEET_PORT", "8000"))
    start_parent_watch()
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info", loop="asyncio", http="h11", ws="none",
                timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SEC)


if __name__ == "__main__":
    main()
