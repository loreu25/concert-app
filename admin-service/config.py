import os

class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql://concert_user:supersecret@postgres:5432/concert_db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Добавляем папку для загрузок
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
