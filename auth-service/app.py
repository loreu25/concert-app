from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import jwt
import os

from models import db, User, RefreshToken
from config import Config


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

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

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5001, debug=True)
