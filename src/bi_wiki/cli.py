import sys

import uvicorn
from pydantic import ValidationError

from bi_wiki.core.config import get_settings
from bi_wiki.core.logging import setup_logging


def main() -> None:
    try:
        settings = get_settings()
    except ValidationError:
        print("CONFIGURATION_ERROR: 请检查 BI_WIKI_ 环境变量或项目根目录的 .env", file=sys.stderr)
        raise SystemExit(2) from None
    setup_logging(
        settings.log_level, log_file=settings.log_file, backup_count=settings.log_backup_count
    )
    uvicorn.run(
        "bi_wiki.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=False,
        log_config=None,
    )
