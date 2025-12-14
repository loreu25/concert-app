from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import jwt
import os
import logging
from flasgger import Swagger

from models import db, User, RefreshToken
from config import Config

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Инициализируем Swagger
    swagger = Swagger(app, template={
        "swagger": "2.0",
        "info": {
            "title": "Auth Service API",
            "description": "API для аутентификации пользователей",
            "version": "1.0.0"
        },
        "host": "localhost:5001",
        "basePath": "/",
        "schemes": ["http", "https"]
    })

    db.init_app(app)

    with app.app_context():
        db.create_all()

        # Создание админа при первом запуске
        admin_email = os.environ.get('ADMIN_EMAIL')
        admin_password = os.environ.get('ADMIN_PASSWORD')

        if admin_email and not User.query.filter_by(email=admin_email).first():
            admin_user = User(
                email=admin_email,
                password_hash=generate_password_hash(admin_password),
                role='admin'
            )
            db.session.add(admin_user)
            db.session.commit()
            print(f'Admin user {admin_email} created.')

    # ----------------------------------------
    # JWT helpers
    # ----------------------------------------
    def create_access_token(user):
        payload = {
            "sub": str(user.id),  # Используем 'sub' (как строку) для идентификатора
            "role": user.role, # Добавляем роль
            "exp": datetime.utcnow() + timedelta(minutes=15)
        }
        return jwt.encode(payload, app.config["JWT_SECRET_KEY"], algorithm="HS256")

    def create_refresh_token(user_id):
        payload = {
            "user_id": user_id,
            "exp": datetime.utcnow() + timedelta(days=30)
        }
        token = jwt.encode(payload, app.config["JWT_REFRESH_SECRET"], algorithm="HS256")

        refresh = RefreshToken(
            user_id=user_id,
            token=token,
            expires_at=datetime.utcnow() + timedelta(days=30)
        )
        db.session.add(refresh)
        db.session.commit()

        return token

    # ----------------------------------------
    # ROUTES
    # ----------------------------------------

    @app.route("/register", methods=["POST"])
    def register():
        """
        Регистрация нового пользователя
        ---
        tags:
          - Authentication
        parameters:
          - name: body
            in: body
            required: true
            schema:
              type: object
              properties:
                email:
                  type: string
                  format: email
                  example: "user@example.com"
                password:
                  type: string
                  format: password
                  example: "mypassword123"
        responses:
          201:
            description: Пользователь успешно зарегистрирован
            schema:
              type: object
              properties:
                message:
                  type: string
                user_id:
                  type: integer
          400:
            description: Email уже зарегистрирован или некорректные данные
        """
        data = request.json
        email = data.get("email")
        password = data.get("password")

        if User.query.filter_by(email=email).first():
            return jsonify({"error": "User already exists"}), 400

        user = User(
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()

        return jsonify({"message": "User registered"}), 201

    @app.route("/login", methods=["POST"])
    def login():
        data = request.json
        email = data.get("email")
        password = data.get("password")

        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({"error": "Invalid credentials"}), 401

        access = create_access_token(user)
        refresh = create_refresh_token(user.id)

        return jsonify({
            "access_token": access,
            "refresh_token": refresh
        })

    @app.route("/refresh", methods=["POST"])
    def refresh():
        data = request.json
        refresh_token = data.get("refresh_token")

        record = RefreshToken.query.filter_by(token=refresh_token).first()
        if not record:
            return jsonify({"error": "Invalid refresh token"}), 401

        try:
            payload = jwt.decode(
                refresh_token,
                app.config["JWT_REFRESH_SECRET"],
                algorithms=["HS256"]
            )
        except:
            return jsonify({"error": "Expired refresh token"}), 401

        new_access = create_access_token(payload["user_id"])
        return jsonify({"access_token": new_access})

    # Глобальный обработчик ошибок
    @app.errorhandler(Exception)
    def handle_exception(error):
        logger.error(f"Unhandled exception: {str(error)}", exc_info=True)
        return jsonify({
            "error": "Internal server error",
            "message": str(error)
        }), 500

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({"error": "Bad request"}), 400

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5001, debug=True)
