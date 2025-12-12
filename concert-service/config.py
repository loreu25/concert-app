import os

class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "BOOKING_DATABASE_URI",
        "postgresql://concert_user:supersecret@postgres:5432/concert_db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    RABBITMQ_URL = os.environ.get(
        "RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/"
    )
