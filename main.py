#!/usr/bin/env python3
"""Command-line entry point for the AI Intelligence Radar."""

import asyncio

from src.application import main

if __name__ == "__main__":
    asyncio.run(main())
