# -*- coding: utf-8 -*-
"""build_info.py dosyasini (yapim zamani, surum, build kimligi) uretir."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "build_info.py"
VERSION = "1.0.0"


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() or "yok"
    except Exception:
        return "yok"


def main() -> int:
    now = datetime.now()
    utc = datetime.now(timezone.utc)
    build_id = hashlib.sha1(f"{utc.isoformat()}|{VERSION}".encode("utf-8")).hexdigest()[:8].upper()

    content = f'''# -*- coding: utf-8 -*-
"""Bu dosya tools/make_build_info.py tarafindan otomatik uretilir. Elle degistirmeyin."""

VERSION = "{VERSION}"
BUILD_DATE = "{now:%d.%m.%Y}"
BUILD_TIME = "{now:%H:%M:%S}"
BUILD_UTC = "{utc:%Y-%m-%dT%H:%M:%SZ}"
BUILD_ID = "{build_id}"
BUILD_TIMESTAMP = {int(now.timestamp())}
GIT_COMMIT = "{git_commit()}"
PYTHON_VERSION = "{sys.version.split()[0]}"
'''
    TARGET.write_text(content, encoding="utf-8")
    print(f"build_info.py yazildi -> surum {VERSION}, build {build_id}, {now:%d.%m.%Y %H:%M:%S}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
