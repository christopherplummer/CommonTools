import uvicorn

from web_tools.config import Settings


def main():
    settings = Settings()
    uvicorn.run(
        "web_tools.main:create_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
        workers=1,
        access_log=False,
    )


if __name__ == "__main__":
    main()
