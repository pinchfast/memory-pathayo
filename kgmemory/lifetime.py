from kgmemory.core.logger import logger
from kgmemory.graph.client import close_db
from kgmemory.initial_data import create_superuser


async def startup() -> None:
    await create_superuser()
    logger.info("kgmemory startup complete")


async def shutdown() -> None:
    await close_db()
    logger.info("kgmemory shutdown complete")
