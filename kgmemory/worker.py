from importlib import import_module

from saq import Queue
from saq.job import CronJob
from tortoise import Tortoise

from .core.config import settings
from .db.config import TORTOISE_ORM
from .monitor.tasks import MONITOR_SCHEDULE
from .reports.scheduled import SCHEDULED_REPORT_SCHEDULE

BACKGROUND_FUNCTIONS = [
    "kgmemory.users.tasks.log_user_email",
    "kgmemory.services.email.send_email_task",
    "kgmemory.memory.tasks.ingest_conversation",
    "kgmemory.memory.tasks.ingest_batch_conversation",
    "kgmemory.reports.tasks.generate_report_task",
    "kgmemory.monitor.tasks.monitor_all_orgs",
]


def import_string(dotted_path: str):
    try:
        module_path, class_name = dotted_path.rsplit(".", 1)
    except ValueError as err:
        raise ImportError(f"{dotted_path} doesn't look like a module path") from err
    module = import_module(module_path)
    try:
        return getattr(module, class_name)
    except AttributeError as err:
        raise ImportError(
            f"Module '{module_path}' does not have attribute '{class_name}'"
        ) from err


FUNCTIONS = [import_string(bg_func) for bg_func in BACKGROUND_FUNCTIONS]


async def startup(_: dict):
    await Tortoise.init(config=TORTOISE_ORM)


async def shutdown(_: dict):
    from .core.redis import close_redis
    from .graph.client import close_db

    await Tortoise.close_connections()
    await close_redis()
    await close_db()


queue = Queue.from_url(str(settings.REDIS_URL))

_CRON_SCHEDULES = {**MONITOR_SCHEDULE, **SCHEDULED_REPORT_SCHEDULE}
_CRON_JOBS = [
    CronJob(function=spec["function"], cron=spec["cron"])
    for spec in _CRON_SCHEDULES.values()
]

settings = {
    "queue": queue,
    "functions": FUNCTIONS,
    "concurrency": 10,
    "startup": startup,
    "shutdown": shutdown,
    "cron_jobs": _CRON_JOBS,
}
