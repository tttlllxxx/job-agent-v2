import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, Goal, Profile, get_db, make_engine
from app.main import app


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    directory = tmp_path / "data"
    for folder in ["uploads", "generated", "backups"]:
        (directory / folder).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings(), "data_dir", directory)
    database_url = f"sqlite:///{directory / 'custom-workspace.db'}"
    monkeypatch.setattr(settings(), "workspace_database_url", database_url)
    engine = make_engine(database_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    for module in [
        "app.database",
        "app.main",
        "app.execution",
        "app.monitoring",
        "app.agent",
    ]:
        monkeypatch.setattr(module + ".Session", factory)
    monkeypatch.setattr("app.main.engine", engine)
    with factory() as db:
        db.add(Profile(id=1, data={"graduation_year": "2028", "in_school": True}))
        db.add(
            Goal(
                id=1,
                name="产品实习",
                direction="AI 产品经理",
                recruitment_type="日常实习",
                constraints={},
                preferences={"cities": ["江苏", "浙江", "上海"]},
            )
        )
        db.commit()
    yield factory
    engine.dispose()


@pytest.fixture
def client(workspace, monkeypatch):
    def database():
        with workspace() as db:
            yield db

    app.dependency_overrides[get_db] = database
    monkeypatch.setattr("app.execution.dispatch", lambda run_id: None)
    with TestClient(app, headers={"X-Workspace-Client": "job-agent"}) as client:
        yield client
    app.dependency_overrides.clear()
