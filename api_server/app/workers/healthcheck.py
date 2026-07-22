from __future__ import annotations

from app.integrations import redis_cache


def main() -> None:
    raise SystemExit(0 if redis_cache.ping() else 1)


if __name__ == "__main__":
    main()
