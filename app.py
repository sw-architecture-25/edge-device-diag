import os
import uvicorn


def main():
    """
    ADD74: App(Entry)
    - 시스템 초기화 및 실행요소 의존성 관리 역할
    - FastAPI 기반 DashboardServer(app)를 기동한다.
    """

    host = os.getenv("EDGE_HOST", "0.0.0.0")
    port = int(os.getenv("EDGE_PORT", "8000"))
    reload_flag = os.getenv("EDGE_RELOAD", "false").lower() in ("1", "true", "yes")

    # config.yaml 경로를 런타임에 바꿀 수 있도록 env로 전달
    # (dashboard_server.py에서 CONFIG_PATH를 읽음)
    os.environ.setdefault("CONFIG_PATH", os.getenv("CONFIG_PATH", "config.yaml"))

    uvicorn.run(
        "dashboard.dashboard_server:app",
        host=host,
        port=port,
        reload=reload_flag,
    )


if __name__ == "__main__":
    main()
