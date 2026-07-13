"""Entrypoint: ``python -m services.bot`` (loads .env, runs polling)."""
from services.bot.app import main

if __name__ == "__main__":
    main()
