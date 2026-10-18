#!/usr/bin/env python3
"""Separate free-edition entrypoint; delegates to the unchanged main.py."""
import asyncio
import os

# This launcher always opts into the free policy, regardless of a stale plan
# value in the local shell or .env.  Credentials, sessions, and bot settings are
# loaded by main.py as before and are not rewritten here.
os.environ["SOROUSH_BOT_PLAN"] = "free"

from main import main


if __name__ == "__main__":
    asyncio.run(main())
