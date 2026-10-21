from app.db.session import engine

try:
    with engine.connect() as connection:
        print("Database connection successful!")
except Exception as error:
    print(f"Database connection failed: {error}")