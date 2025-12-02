# app.py
import uvicorn


def main():
    """
    ADD74: App(Entry)
    - 시스템 초기화 및 실행요소 의존성 관리 역할
    - FastAPI 기반 DashboardServer(app)를 기동한다.
    """
    uvicorn.run(
        "dashboard.dashboard_server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()

