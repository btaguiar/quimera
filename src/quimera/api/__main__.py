"""Sobe o servidor da demo: ``python -m quimera.api`` (extra [api]).

Usa uvicorn; host/port vêm de ``API_HOST``/``PORT`` (o Cloud Run injeta
``PORT``).
"""

from __future__ import annotations

import logging
import os


def main() -> int:
    import uvicorn

    from . import create_app

    # Sem isso o INFO de quimera.* (custo e bytes por pedido) não chega ao log.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s %(message)s")

    uvicorn.run(
        create_app(warmup=True),
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
