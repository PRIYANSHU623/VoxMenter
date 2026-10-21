
from app.db.session import Base, engine

# Register all models with the shared SQLAlchemy Base.
from app import models  # noqa: F401


def init_db():
    Base.metadata.create_all(bind=engine)
    print("VoxMenter database tables created successfully.")


if __name__ == "__main__":
    init_db()
