"""Startet den Server mit `python -m app` (Host/Port aus der .env)."""

import uvicorn

from .config import bootstrap_env, load_config


def main() -> None:
    bootstrap_env()
    config = load_config()
    uvicorn.run(
        "app.main:app",
        host=config.host,
        port=config.port,
        ssl_certfile=str(config.ssl_certfile) if config.ssl_certfile else None,
        ssl_keyfile=str(config.ssl_keyfile) if config.ssl_keyfile else None,
    )


if __name__ == "__main__":
    main()
