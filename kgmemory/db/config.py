from fastapi import FastAPI
from kgmemory.core.config import settings
from tortoise.contrib.fastapi import register_tortoise

TORTOISE_ORM = {
    "connections": {"default": str(settings.DATABASE_URI)},
    "apps": {
        "models": {
            "models": [
                "kgmemory.users.models",
                "kgmemory.orgs.models",
                "aerich.models",
            ],
            "default_connection": "default",
        },
    },
}


def register_db(app: FastAPI) -> None:
    register_tortoise(
        app,
        config=TORTOISE_ORM,
        generate_schemas=False,
        add_exception_handlers=True,
    )
