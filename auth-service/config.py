import os

class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "AUTH_DATABASE_URI",
        "postgresql://concert_user:supersecret@postgres:5432/concert_db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
    JWT_REFRESH_SECRET = os.environ.get("JWT_REFRESH_SECRET")
