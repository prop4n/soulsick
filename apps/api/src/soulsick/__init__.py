__version__ = "0.1.0"


def main() -> None:
    import uvicorn

    from .config import get_env

    env = get_env()
    uvicorn.run("soulsick.app:create_app", factory=True, host=env.host, port=env.port, log_level="info")
