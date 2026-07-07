from importlib import import_module

from saq import Queue
from tortoise import Tortoise

from .core.config import settings
from .db.config import TORTOISE_ORM

BACKGROUND_FUNCTIONS = [
    "knowledgegraph for pinchfast.users.tasks.log_user_email",
    "knowledgegraph for pinchfast.services.email.send_email_task",
]


def import_string(dotted_path: str):
    """
    Import a module, or resolve an attribute of a module.
    """
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
    """
    Binds a connection set to the db object.
    """
    await Tortoise.init(config=TORTOISE_ORM)


async def shutdown(_: dict):
    """
    Pops the bind on the db object.
    """
    await Tortoise.close_connections()


queue = Queue.from_url(str(settings.REDIS_URL))

settings = {
    "queue": queue,
    "functions": FUNCTIONS,
    "concurrency": 10,
    "startup": startup,
    "shutdown": shutdown,
}
