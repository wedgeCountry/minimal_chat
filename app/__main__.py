"""Startet den Server mit `python -m app` (Host/Port aus der .env)."""

import uvicorn

from .config import bootstrap_env, load_config


def main() -> None:
    bootstrap_env()
    config = load_config()
    uvicorn.run("app.main:app", host=config.host, port=config.port)


if __name__ == "__main__":
    main()
