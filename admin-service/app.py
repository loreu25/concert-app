import os
import flask
import logging
import pika
import json
import threading
import time
import uuid
from flask import Flask, request, jsonify
from flask_jwt_extended import JWTManager, jwt_required, get_jwt, decode_token
from werkzeug.utils import secure_filename
from datetime import datetime
from flasgger import Swagger

from config import Config
from models import db, Concert, TicketType, Artist, Booking

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config['JSON_SORT_KEYS'] = False
    jwt = JWTManager(app)
    
    # Инициализируем Swagger для документации API
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
    
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)

    with app.app_context():
        db.create_all()

    def admin_required(f):
        from functools import wraps
        @wraps(f)
        @jwt_required()
        def decorated(*args, **kwargs):
            claims = get_jwt()
            if claims.get('role') != 'admin':
                return jsonify({"error": "Доступ запрещён"}), 403
            return f(*args, **kwargs)

        return decorated

    @app.route('/admin/create_concert', methods=['POST'])
    @admin_required
    def create_concert():
        """
        Создание нового концерта
        ---
        tags:
          - Concerts
        parameters:
          - name: body
            in: body
            required: true
            schema:
              type: object
              properties:
                title:
                  type: string
                  example: "Metallica - Master of Puppets Tour"
                description:
                  type: string
                  example: "Epic concert by Metallica"
                date:
                  type: string
                  format: date-time
                  example: "2025-12-25 20:00"
                image_url:
                  type: string
                  example: "https://example.com/image.jpg"
                artist_ids:
                  type: array
                  items:
                    type: integer
                  example: [1, 2, 3]
        responses:
          201:
            description: Концерт успешно создан
          400:
            description: Ошибка валидации (дата в прошлом, неверный формат или концерт уже существует)
          403:
            description: Доступ запрещён (требуется роль admin)
        """
        data = request.json
        title = data.get("title")
        description = data.get("description")
        date_str = data.get("date")
        image_url = data.get("image_url")
        artist_ids = data.get("artist_ids", [])

        if not title or not date_str:
            return jsonify({"error": "Title and date are required"}), 400

        try:
            date = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD HH:MM"}), 400

        if date <= datetime.utcnow():
            return jsonify({"error": "Concert date must be in the future"}), 400

        if Concert.query.filter_by(title=title).first():
            return jsonify({"error": "Concert already exists"}), 400

        concert = Concert(
            title=title,
            description=description,
            date=date,
            image_url=image_url,
            created_at=datetime.utcnow()
        )

        for artist_id in artist_ids:
            artist = Artist.query.get(artist_id)
            if artist:
                concert.artists.append(artist)

        db.session.add(concert)
        db.session.commit()

        return jsonify({"message": "Concert registered"}), 201

    @app.route('/concerts', methods=['GET'])
    def list_concerts():
        """
        Получить список всех концертов
        ---
        tags:
          - Concerts
        responses:
          200:
            description: Список всех концертов
            schema:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  title:
                    type: string
                  date:
                    type: string
                    format: date-time
                  image_url:
                    type: string
                  artists:
                    type: array
                    items:
                      type: string
                  ticket_types:
                    type: array
        """
        concerts = Concert.query.all()
        data = []
        for c in concerts:
            data.append({
                "id": c.id,
                "title": c.title,
                "date": c.date.strftime('%Y-%m-%d %H:%M'),
                "image_url": c.image_url,
                "artists": [a.name for a in c.artists] or [],
                "ticket_types": [
                    {
                        "id": t.id,
                        "type": t.type,
                        "price": str(t.price),
                        "total_quantity": t.total_quantity,
                        "available_quantity": t.total_quantity - sum(b.quantity for b in t.bookings)
                    } for t in c.ticket_types
                ]
            })
        return jsonify(data)

    @app.route('/concerts/<int:concert_id>', methods=['GET'])
    def get_concert(concert_id):
        """
        Получить информацию о конкретном концерте
        ---
        tags:
          - Concerts
        parameters:
          - in: path
            name: concert_id
            type: integer
            required: true
            description: ID концерта
        responses:
          200:
            description: Информация о концерте
            schema:
              type: object
              properties:
                id:
                  type: integer
                title:
                  type: string
                description:
                  type: string
                date:
                  type: string
                  format: date-time
                image_url:
                  type: string
                artists:
                  type: array
                  items:
                    type: string
                ticket_types:
                  type: array
          404:
            description: Концерт не найден
        """
        concert = Concert.query.get(concert_id)

        if not concert:
            return jsonify({"error": "Concert not found"}), 404

        return jsonify({
        "id": concert.id,
        "title": concert.title,
        "description": concert.description,
        "date": concert.date.isoformat() if concert.date else None,
        "image_url": concert.image_url,
        "artists": [a.name for a in concert.artists],
        "ticket_types": [
            {
                "id": t.id,
                "type": t.type,
                "price": str(t.price),
                "total_quantity": t.total_quantity,
                "available_quantity": t.total_quantity - sum(b.quantity for b in t.bookings)
            } for t in concert.ticket_types
        ]
    })

    @app.route('/admin/concerts/<int:concert_id>', methods=['PUT'])
    @admin_required
    def update_concert(concert_id):
        """
        Обновить информацию о концерте
        ---
        tags:
          - Concerts
        parameters:
          - in: path
            name: concert_id
            type: integer
            required: true
            description: ID концерта
          - in: body
            name: body
            required: true
            schema:
              type: object
              properties:
                title:
                  type: string
                description:
                  type: string
                date:
                  type: string
                  format: date-time
                  example: "2025-12-25 20:00"
                image_url:
                  type: string
                artists:
                  type: array
                  items:
                    type: integer
        responses:
          200:
            description: Концерт успешно обновлён
          400:
            description: Ошибка валидации
          404:
            description: Концерт не найден
          403:
            description: Доступ запрещён (требуется роль admin)
        """
        try:
            concert = Concert.query.get(concert_id)
            if not concert:
                return jsonify({"error": "Concert not found"}), 404

            data = request.json
            if not data:
                return jsonify({"error": "No data provided"}), 400

            if 'title' in data:
                concert.title = data['title']
            if 'description' in data:
                concert.description = data['description']
            if 'date' in data:
                try:
                    concert.date = datetime.strptime(data['date'], "%Y-%m-%d %H:%M")
                except ValueError:
                    return jsonify({"error": "Invalid date format. Use YYYY-MM-DD HH:MM"}), 400
            if 'image_url' in data:
                concert.image_url = data['image_url']

            if 'artists' in data:
                artist_ids = data['artists']  # ожидаем список id
                from models import Artist  # импортируем Artist здесь
                concert.artists = Artist.query.filter(Artist.id.in_(artist_ids)).all()

            db.session.commit()

            return jsonify({
                "message": "Concert updated successfully",
                "concert": {
                    "id": concert.id,
                    "title": concert.title,
                    "date": concert.date.strftime('%Y-%m-%d %H:%M') if concert.date else None,
                    "artists": [{"id": a.id, "name": a.name} for a in concert.artists],
                    "ticket_types": [
                        {
                            "id": t.id,
                            "type": t.type,
                            "price": t.price,
                            "total_quantity": t.total_quantity
                        } for t in concert.ticket_types
                    ]
                }
            }), 200

        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route("/admin/concerts/<int:concert_id>", methods=["DELETE"])
    @admin_required
    def delete_concert(concert_id):
        """
        Удалить концерт
        ---
        tags:
          - Concerts
        parameters:
          - in: path
            name: concert_id
            type: integer
            required: true
            description: ID концерта
        responses:
          200:
            description: Концерт успешно удалён
          404:
            description: Концерт не найден
          403:
            description: Доступ запрещён (требуется роль admin)
        """
        try:
            concert = Concert.query.get(concert_id)
            if not concert:
                return jsonify({"error": "Concert not found"}), 404

            db.session.delete(concert)
            db.session.commit()

            return jsonify({"message": "Concert deleted successfully"}), 200

        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/admin/concerts/<int:concert_id>/ticket_types', methods=["POST"])
    @admin_required
    def add_ticket_type(concert_id):
        """
        Добавить тип билета к концерту
        ---
        tags:
          - Ticket Types
        parameters:
          - in: path
            name: concert_id
            type: integer
            required: true
            description: ID концерта
          - in: body
            name: body
            required: true
            schema:
              type: object
              properties:
                type:
                  type: string
                  example: "VIP"
                price:
                  type: number
                  example: 150.00
                total_quantity:
                  type: integer
                  example: 100
        responses:
          201:
            description: Тип билета успешно добавлен
          400:
            description: Ошибка валидации
          404:
            description: Концерт не найден
          403:
            description: Доступ запрещён (требуется роль admin)
        """
        concert = Concert.query.get(concert_id)

        if not concert:
            return jsonify({"error": "Concert not found"}), 404

        data = request.json
        type = data.get("type")
        price = data.get("price")
        total_quantity = data.get("total_quantity")

        if total_quantity < 0:
            return jsonify({"error": "Quantity must be non-negative"}), 400

        if  price < 0:
            return jsonify({"error": "Price must be non-negative"}), 400

        if not all([type, price, total_quantity]):
            return jsonify({"error": "Name, price and quantity are required"}), 400

        ticket_type = TicketType(
            concert_id=concert.id,
            type=type,
            price=price,
            total_quantity=total_quantity
        )

        db.session.add(ticket_type)
        db.session.commit()

        return jsonify({"message": "Ticket type added successfully"}), 201

    @app.route('/admin/artists', methods=["POST"])
    @admin_required
    def create_artist():
        """
        Создание нового артиста
        ---
        tags:
          - Artists
        parameters:
          - name: body
            in: body
            required: true
            schema:
              type: object
              properties:
                name:
                  type: string
                  example: "Metallica"
                description:
                  type: string
                  example: "Legendary heavy metal band"
                genre:
                  type: string
                  example: "Heavy Metal"
                image_url:
                  type: string
                  example: "https://example.com/metallica.jpg"
        responses:
          201:
            description: Артист успешно создан
          400:
            description: Ошибка валидации
          403:
            description: Доступ запрещён (требуется роль admin)
        """
        data = request.json
        name = data.get("name")
        description = data.get("description")
        genre = data.get("genre")
        image_url = data.get("image_url")

        if not all([name, description, genre, image_url]):
            logger.warning("Create artist failed: missing required fields")
            return jsonify({"error": "Name, description, image_url and genre are required"}), 400

        if Artist.query.filter_by(name=name).first():
            logger.warning(f"Artist already exists: {name}")
            return jsonify({"error": "Artist already exists"}), 400

        artist = Artist(
            name=name,
            description=description,
            genre=genre,
            image_url=image_url
        )

        db.session.add(artist)
        db.session.commit()
        logger.info(f"Artist created: {artist.id} - {name}")

        return jsonify({
            "message": "Artist added successfully",
            "artist": {
                "id": artist.id,
                "name": artist.name,
                "genre": artist.genre
            }
        }), 201
    
    @app.route('/artists', methods=['GET'])
    def list_artists():
        """
        Get all artists
        ---
        tags:
          - Artists
        responses:
          200:
            description: List of all artists
            schema:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  name:
                    type: string
                  description:
                    type: string
                  genre:
                    type: string
                  image_url:
                    type: string
        """
        artists = Artist.query.all()
        data = []
        for a in artists:
            data.append({
                "id": a.id,
                "name": a.name,
                "description": a.description,
                "genre": a.genre,
                "image_url": a.image_url
            })
        return jsonify(data)
    
    @app.route('/artists/<int:artist_id>', methods=['GET'])
    def get_artist(artist_id):
        """
        Get artist by ID
        ---
        tags:
          - Artists
        parameters:
          - in: path
            name: artist_id
            type: integer
            required: true
            description: Artist ID
        responses:
          200:
            description: Artist details
            schema:
              type: object
              properties:
                id:
                  type: integer
                name:
                  type: string
                description:
                  type: string
                genre:
                  type: string
                image_url:
                  type: string
          404:
            description: Artist not found
        """
        artist = Artist.query.get(artist_id)
        if not artist:
            logger.warning(f"Artist {artist_id} not found")
            return jsonify({"error": "Artist not found"}), 404
        
        return jsonify({
            "id": artist.id,
            "name": artist.name,
            "description": artist.description,
            "genre": artist.genre,
            "image_url": artist.image_url
        })
    
    @app.route('/my-bookings', methods=['GET'])
    @jwt_required()
    def get_my_bookings():
        """
        Получить мои бронирования
        ---
        tags:
          - Bookings
        security:
          - Bearer: []
        responses:
          200:
            description: Список бронирований текущего пользователя
            schema:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: string
                    format: uuid
                  concert_id:
                    type: integer
                  ticket_type_id:
                    type: integer
                  quantity:
                    type: integer
                  status:
                    type: string
                  created_at:
                    type: string
                    format: date-time
          401:
            description: Требуется аутентификация
        """
        user_id = get_jwt()['sub']
        bookings = Booking.query.filter_by(user_id=user_id).all()

        data = []
        for booking in bookings:
            data.append({
                "id": booking.id,
                "concert_id": booking.concert_id,
                "ticket_type_id": booking.ticket_type_id,
                "quantity": booking.quantity,
                "status": booking.status,
                "created_at": booking.created_at.isoformat()
            })
        
        return jsonify(data)


    @app.route('/bookings', methods=['POST'])
    @jwt_required()
    def create_booking():
        """
        Создать новое бронирование
        ---
        tags:
          - Bookings
        security:
          - Bearer: []
        parameters:
          - in: body
            name: body
            required: true
            schema:
              type: object
              properties:
                concert_id:
                  type: integer
                  example: 1
                ticket_type_id:
                  type: integer
                  example: 1
                quantity:
                  type: integer
                  example: 2
        responses:
          201:
            description: Бронирование принято в обработку
            schema:
              type: object
              properties:
                message:
                  type: string
                booking_id:
                  type: string
                  format: uuid
                status:
                  type: string
          400:
            description: Ошибка валидации (недостаточно билетов или невернные параметры)
          404:
            description: Концерт или тип билета не найден
          401:
            description: Требуется аутентификация
        """
        data = request.json
        concert_id = data.get('concert_id')
        ticket_type_id = data.get('ticket_type_id')
        quantity = data.get('quantity')

        if not all([concert_id, ticket_type_id, quantity]):
            return jsonify({"error": "concert_id, ticket_type_id and quantity are required"}), 400

        if not isinstance(quantity, int) or quantity <= 0:
            return jsonify({"error": "Quantity must be a positive integer"}), 400

        ticket_type = TicketType.query.get(ticket_type_id)
        if not ticket_type or ticket_type.concert_id != concert_id:
            return jsonify({"error": "Ticket type not found for this concert"}), 404

        booking_id = str(uuid.uuid4())
        user_id = get_jwt()['sub']

        def send_to_queue():
            try:
                connection = pika.BlockingConnection(
                    pika.ConnectionParameters(
                        host='rabbitmq',
                        port=5672,
                        credentials=pika.PlainCredentials('guest', 'guest'),
                        connection_attempts=3,
                        retry_delay=2
                    )
                )
                channel = connection.channel()
                channel.queue_declare(queue='booking_queue', durable=True)
                
                message = {
                    'booking_id': booking_id,
                    'user_id': user_id,
                    'concert_id': concert_id,
                    'ticket_type_id': ticket_type_id,
                    'quantity': quantity
                }
                channel.basic_publish(
                    exchange='',
                    routing_key='booking_queue',
                    body=json.dumps(message),
                    properties=pika.BasicProperties(delivery_mode=2)
                )
                connection.close()
                logger.info(f"Booking event {booking_id} sent to RabbitMQ for processing")
            
            except Exception as e:
                logger.error(f"Failed to send booking event {booking_id} to RabbitMQ: {str(e)}")
        
        queue_thread = threading.Thread(target=send_to_queue, daemon=True)
        queue_thread.start()

        return jsonify({
            "message": "Booking request accepted for processing",
            "booking_id": booking_id,
            "status": "processing"
        }), 201


    @app.route('/admin/statistics', methods=['GET'])
    @admin_required
    def get_statistics():
        """
        Получение общей статистики по системе
        ---
        tags:
          - Statistics
        responses:
          200:
            description: Общая статистика системы
            schema:
              type: object
              properties:
                total_revenue:
                  type: number
                  example: 15000.50
                total_tickets_sold:
                  type: integer
                  example: 245
                active_concerts_count:
                  type: integer
                  example: 12
                average_booking_value:
                  type: number
                  example: 61.22
          403:
            description: Доступ запрещён (требуется роль admin)
        """
        try:
            total_revenue = db.session.query(db.func.sum(Booking.quantity * TicketType.price)) \
                .join(TicketType, Booking.ticket_type_id == TicketType.id) \
                .scalar() or 0

            total_tickets_sold = db.session.query(db.func.sum(Booking.quantity)).scalar() or 0

            active_concerts_count = Concert.query.filter(Concert.date >= datetime.utcnow()).count()

            total_bookings = Booking.query.count()
            average_booking_value = float(total_revenue) / total_bookings if total_bookings > 0 else 0

            logger.info("Statistics retrieved successfully")

            return jsonify({
                "total_revenue": float(total_revenue),
                "total_tickets_sold": int(total_tickets_sold),
                "active_concerts_count": active_concerts_count,
                "total_bookings": total_bookings,
                "average_booking_value": round(average_booking_value, 2)
            }), 200

        except Exception as e:
            logger.error(f"Failed to get statistics: {str(e)}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.route('/admin/statistics/concerts', methods=['GET'])
    @admin_required
    def get_concert_statistics():
        """
        Получение статистики по каждому концерту
        ---
        tags:
          - Statistics
        responses:
          200:
            description: Статистика по всем концертам
            schema:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  title:
                    type: string
                  date:
                    type: string
                  occupancy_percent:
                    type: number
                  total_revenue:
                    type: number
                  tickets_sold:
                    type: integer
                  most_popular_ticket_type:
                    type: string
          403:
            description: Доступ запрещён (требуется роль admin)
        """
        try:
            concerts = Concert.query.all()
            concert_stats = []

            for concert in concerts:
                total_tickets_available = db.session.query(db.func.sum(TicketType.total_quantity)) \
                    .filter(TicketType.concert_id == concert.id).scalar() or 0

                total_tickets_sold = db.session.query(db.func.sum(Booking.quantity)) \
                    .filter(Booking.concert_id == concert.id).scalar() or 0

                occupancy = (float(total_tickets_sold) / float(total_tickets_available) * 100) \
                    if total_tickets_available > 0 else 0

                revenue = db.session.query(db.func.sum(Booking.quantity * TicketType.price)) \
                    .join(TicketType, Booking.ticket_type_id == TicketType.id) \
                    .filter(Booking.concert_id == concert.id).scalar() or 0

                popular_ticket_query = db.session.query(
                    TicketType.type,
                    db.func.sum(Booking.quantity).label('total_sold')
                ) \
                    .join(Booking, TicketType.id == Booking.ticket_type_id) \
                    .filter(TicketType.concert_id == concert.id) \
                    .group_by(TicketType.type) \
                    .order_by(db.desc('total_sold')) \
                    .first()

                most_popular_ticket = popular_ticket_query[0] if popular_ticket_query else "N/A"

                concert_stats.append({
                    "id": concert.id,
                    "title": concert.title,
                    "date": concert.date.strftime('%Y-%m-%d %H:%M'),
                    "occupancy_percent": round(occupancy, 2),
                    "total_revenue": float(revenue),
                    "tickets_sold": int(total_tickets_sold),
                    "tickets_available": int(total_tickets_available),
                    "most_popular_ticket_type": most_popular_ticket
                })

            logger.info(f"Concert statistics retrieved for {len(concert_stats)} concerts")
            return jsonify(concert_stats), 200

        except Exception as e:
            logger.error(f"Failed to get concert statistics: {str(e)}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @app.route("/admin/upload_image", methods=["POST"])
    @admin_required
    def upload_image():
        """
        Загрузка изображения (для концертов и артистов)
        ---
        tags:
          - Files
        consumes:
          - multipart/form-data
        parameters:
          - name: image
            in: formData
            type: file
            required: true
            description: Изображение (PNG, JPG, JPEG, WEBP)
        responses:
          200:
            description: Изображение успешно загружено
            schema:
              type: object
              properties:
                image_url:
                  type: string
                  example: "http://localhost/admin/static/image.jpg"
          400:
            description: Ошибка - файл отсутствует или недопустимый формат
          403:
            description: Доступ запрещён (требуется роль admin)
        """
        if "image" not in request.files:
            logger.warning("Upload image failed: No file part in request")
            return jsonify({"error": "No file part"}), 400

        file = request.files["image"]

        if file.filename == "":
            logger.warning("Upload image failed: No selected file")
            return jsonify({"error": "No selected file"}), 400

        if not allowed_file(file.filename):
            logger.warning(f"Upload image failed: Invalid file type - {file.filename}")
            return jsonify({"error": "Invalid file type. Allowed: png, jpg, jpeg, webp"}), 400

        try:
            filename = secure_filename(file.filename)
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(save_path)

            # URL для доступа к файлу через Nginx
            image_url = f"http://localhost/admin/static/{filename}"
            logger.info(f"Image uploaded successfully: {filename}")

            return jsonify({"image_url": image_url}), 200
        except Exception as e:
            logger.error(f"Upload image failed: {str(e)}", exc_info=True)
            return jsonify({"error": f"Failed to upload image: {str(e)}"}), 500

    # Раздаем статические файлы из папки uploads
    @app.route('/admin/static/<path:filename>')
    @admin_required
    def static_files(filename):
        """
        Получить загруженный файл (изображение)
        ---
        tags:
          - Files
        parameters:
          - in: path
            name: filename
            type: string
            required: true
            description: Имя файла
        responses:
          200:
            description: Файл найден и возвращён
          404:
            description: Файл не найден
          403:
            description: Доступ запрещён (требуется роль admin)
        """
        return flask.send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @app.route('/admin/artists/<int:artist_id>', methods=['PUT'])
    @admin_required
    def update_artist(artist_id):
        """
        Обновление информации об артисте
        ---
        tags:
          - Artists
        parameters:
          - name: artist_id
            in: path
            type: integer
            required: true
          - name: body
            in: body
            schema:
              type: object
              properties:
                name:
                  type: string
                description:
                  type: string
                genre:
                  type: string
                image_url:
                  type: string
        responses:
          200:
            description: Артист успешно обновлён
          404:
            description: Артист не найден
          403:
            description: Доступ запрещён (требуется роль admin)
        """
        artist = Artist.query.get(artist_id)
        if not artist:
            return jsonify({"error": "Artist not found"}), 404

        data = request.json
        if 'name' in data:
            artist.name = data['name']
        if 'description' in data:
            artist.description = data['description']
        if 'genre' in data:
            artist.genre = data['genre']
        if 'image_url' in data:
            artist.image_url = data['image_url']

        db.session.commit()
        logger.info(f"Artist updated: {artist_id}")

        return jsonify({
            "message": "Artist updated successfully",
            "artist": {
                "id": artist.id,
                "name": artist.name,
                "genre": artist.genre
            }
        }), 200

    @app.route('/admin/artists/<int:artist_id>', methods=['DELETE'])
    @admin_required
    def delete_artist(artist_id):
        """
        Удаление артиста
        ---
        tags:
          - Artists
        parameters:
          - name: artist_id
            in: path
            type: integer
            required: true
        responses:
          200:
            description: Артист успешно удалён
          404:
            description: Артист не найден
          403:
            description: Доступ запрещён (требуется роль admin)
        """
        artist = Artist.query.get(artist_id)
        if not artist:
            return jsonify({"error": "Artist not found"}), 404

        db.session.delete(artist)
        db.session.commit()
        logger.info(f"Artist deleted: {artist_id}")

        return jsonify({"message": "Artist deleted successfully"}), 200

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


def run_consumer():
    """
    RabbitMQ Consumer для асинхронной обработки бронирований
    Получает событие бронирования, проверяет доступность билетов и СОЗДАЕТ booking в БД
    """
    while True:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
            channel = connection.channel()
            channel.queue_declare(queue='booking_queue', durable=True)

            def callback(ch, method, properties, body):
                app = create_app()
                with app.app_context():
                    try:
                        message = json.loads(body)
                        booking_id = message.get('booking_id')
                        user_id = message.get('user_id')
                        concert_id = message.get('concert_id')
                        ticket_type_id = message.get('ticket_type_id')
                        quantity = message.get('quantity')

                        logger.info(f"[Consumer] Processing booking event {booking_id} for user {user_id}")

                        # Валидируем данные
                        if not all([booking_id, user_id, concert_id, ticket_type_id, quantity]):
                            logger.error(f"[Consumer] Invalid message format: {message}")
                            ch.basic_ack(delivery_tag=method.delivery_tag)
                            return

                        # Получаем тип билета
                        ticket_type = TicketType.query.get(ticket_type_id)
                        if not ticket_type or ticket_type.concert_id != concert_id:
                            logger.warning(f"[Consumer] TicketType {ticket_type_id} not found for concert {concert_id}")
                            ch.basic_ack(delivery_tag=method.delivery_tag)
                            return

                        # Проверяем доступность билетов
                        booked_quantity = sum(
                            b.quantity for b in ticket_type.bookings 
                            if b.status in ['confirmed', 'pending']
                        )
                        available_quantity = ticket_type.total_quantity - booked_quantity

                        if quantity > available_quantity:
                            logger.warning(
                                f"[Consumer] Not enough tickets for booking {booking_id}. "
                                f"Available: {available_quantity}, Requested: {quantity}"
                            )
                            ch.basic_ack(delivery_tag=method.delivery_tag)
                            return

                        booking = Booking(
                            id=booking_id,
                            user_id=user_id,
                            concert_id=concert_id,
                            ticket_type_id=ticket_type_id,
                            quantity=quantity,
                            status='confirmed'
)
                        
                        db.session.add(booking)
                        db.session.commit()
                        logger.info(f"[Consumer] Booking {booking_id} created and confirmed successfully")

                    except Exception as e:
                        logger.error(f"[Consumer] Error processing booking event: {e}", exc_info=True)
                        db.session.rollback()

                    finally:
                        ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue='booking_queue', on_message_callback=callback)
            logger.info('[Consumer] Started, waiting for messages...')
            channel.start_consuming()

        except pika.exceptions.AMQPConnectionError as e:
            logger.error(f"[Consumer] Connection failed, retrying in 5 seconds: {e}")
            time.sleep(5)


if __name__ == "__main__":
    app = create_app()
    consumer_thread = threading.Thread(target=run_consumer, daemon=True)
    consumer_thread.start()
    logger.info("Starting admin-service on port 5003")
    app.run(host="0.0.0.0", port=5003, debug=False)
