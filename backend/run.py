import os

import uvicorn

from app.main import app as fastapi_app


def main() -> None:
    host = os.getenv("DRUMSHEET_HOST", "127.0.0.1")
    port = int(os.getenv("DRUMSHEET_PORT", "8000"))
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info", loop="asyncio", http="h11", ws="none")


if __name__ == "__main__":
    main()
