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
    app.config['JSON_SORT_KEYS'] = False

    swagger_config = {
        "headers": [],
        "specs": [
            {
                "endpoint": 'apispec',
                "route": '/apispec.json',
                "rule_filter": lambda rule: True,
                "model_filter": lambda tag: True,
            }
        ],
        "static_url_path": "/flasgger_static",
        "swagger_ui": True,
        "specs_route": "/apidocs/"
    }
    swagger = Swagger(app, config=swagger_config)

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


    def create_access_token(user):
        payload = {
            "sub": str(user.id),
            "role": user.role,
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
                  example: "user@example.com"
                password:
                  type: string
                  example: "securepassword123"
        responses:
          201:
            description: Пользователь успешно зарегистрирован
          400:
            description: Пользователь уже существует или ошибка валидации
        """
        data = request.json
        email = data.get("email")
        password = data.get("password")

        if not email or not password:
            logger.warning("Registration failed: missing email or password")
            return jsonify({"error": "Email and password are required"}), 400

        if User.query.filter_by(email=email).first():
            logger.warning(f"Registration failed: user already exists - {email}")
            return jsonify({"error": "User already exists"}), 400

        user = User(
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        logger.info(f"User registered: {email}")

        return jsonify({"message": "User registered"}), 201

    @app.route("/login", methods=["POST"])
    def login():
        """
        Вход пользователя и получение JWT токена
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
                  example: "user@example.com"
                password:
                  type: string
                  example: "securepassword123"
        responses:
          200:
            description: Успешный вход, возвращены токены
            schema:
              type: object
              properties:
                access_token:
                  type: string
                refresh_token:
                  type: string
          401:
            description: Неверные учётные данные
        """
        data = request.json
        email = data.get("email")
        password = data.get("password")

        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            logger.warning(f"Login failed for email: {email}")
            return jsonify({"error": "Invalid credentials"}), 401

        access = create_access_token(user)
        refresh = create_refresh_token(user.id)
        logger.info(f"User logged in: {email}")

        return jsonify({
            "access_token": access,
            "refresh_token": refresh
        })

    @app.route("/refresh", methods=["POST"])
    def refresh():
        """
        Обновление access токена с помощью refresh токена
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
                refresh_token:
                  type: string
                  example: "eyJ0eXAiOiJKV1QiLCJhbGc..."
        responses:
          200:
            description: Новый access token
            schema:
              type: object
              properties:
                access_token:
                  type: string
          401:
            description: Неверный или истекший refresh token
        """
        data = request.json
        refresh_token = data.get("refresh_token")

        record = RefreshToken.query.filter_by(token=refresh_token).first()
        if not record:
            logger.warning("Refresh failed: invalid refresh token")
            return jsonify({"error": "Invalid refresh token"}), 401

        try:
            payload = jwt.decode(
                refresh_token,
                app.config["JWT_REFRESH_SECRET"],
                algorithms=["HS256"]
            )
        except Exception as e:
            logger.error(f"Refresh token validation failed: {e}")
            return jsonify({"error": "Expired refresh token"}), 401

        user = User.query.get(payload["user_id"])
        new_access = create_access_token(user)
        logger.info(f"Token refreshed for user: {user.email}")
        return jsonify({"access_token": new_access})

    # Глобальные обработчики ошибок
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
    logger.info("Starting auth-service on port 5001")
    app.run(host="0.0.0.0", port=5001, debug=False)
