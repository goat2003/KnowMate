from __future__ import annotations

import logging

from app.config import load_settings
from app.grpc_server import serve


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    serve(settings)


if __name__ == "__main__":
    main()
