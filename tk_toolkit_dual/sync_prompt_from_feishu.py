#!/usr/bin/env python3
from __future__ import annotations

import sys

from prompt_config_sync import main


if __name__ == "__main__":
    main(["from-feishu", *sys.argv[1:]])
