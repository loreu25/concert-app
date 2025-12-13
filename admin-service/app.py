import os
import flask
from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_jwt_extended import JWTManager, jwt_required, get_jwt
from werkzeug.utils import secure_filename
from datetime import datetime
import pika
import json
import threading
import time
from flask_jwt_extended import create_access_token, decode_token

from config import Config
from models import db, Concert, TicketType, Artist, Booking

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Настраиваем JWT для чтения токена из cookie
    app.config["JWT_TOKEN_LOCATION"] = ["headers", "cookies"]
    app.config["JWT_ACCESS_COOKIE_NAME"] = "access_token"
    app.config["JWT_COOKIE_CSRF_PROTECT"] = False # В реальном приложении лучше включить
    jwt = JWTManager(app)
    # Создаем папку для загрузок, если нет
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

    @app.route('/api/admin/create_concert', methods=['POST'])
    @admin_required
    def create_concert():
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

    @app.route('/api/concerts', methods=['GET'])
    def list_concerts():
        concerts = Concert.query.all()
        data = []
        for c in concerts:
            data.append({
                "id": c.id,
                "title": c.title,
                "date": c.date.strftime('%Y-%m-%d %H:%M'),
                "image_url": c.image_url,
                "artists": [{"id": a.id, "name": a.name} for a in c.artists] or [],
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

    @app.route('/api/concerts/<int:concert_id>', methods=['GET'])
    def get_concert(concert_id):
        concert = Concert.query.get(concert_id)

        if not concert:
            return jsonify({"error": "Concert not found"}), 404

        return jsonify({
        "id": concert.id,
        "title": concert.title,
        "description": concert.description,
        "date": concert.date.isoformat() if concert.date else None,
        "image_url": concert.image_url,
        "artists": [{"id": a.id, "name": a.name} for a in concert.artists],
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

    @app.route('/api/admin/concerts/<int:concert_id>', methods=['PUT'])
    @admin_required
    def update_concert(concert_id):
        try:
            concert = Concert.query.get(concert_id)
            if not concert:
                return jsonify({"error": "Concert not found"}), 404

            data = request.json
            if not data:
                return jsonify({"error": "No data provided"}), 400

            # Обновление простых полей
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

            # Обновление артистов (список id)
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

    @app.route("/api/admin/concerts/<int:concert_id>", methods=["DELETE"])
    @admin_required
    def delete_concert(concert_id):
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

    @app.route('/api/admin/concerts/<int:concert_id>/ticket_types', methods=["POST"])
    @admin_required
    def add_ticket_type(concert_id):
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

    @app.route('/api/admin/concerts/<int:concert_id>/artists', methods=["POST"])
    @admin_required
    def create_artist(concert_id):
        concert = Concert.query.get(concert_id)
        if not concert:
            return jsonify({"error": "Concert not found"}), 404

        data = request.json
        name = data.get("name")
        description = data.get("description")
        genre = data.get("genre")
        image_url = data.get("image_url")

        if not all([name, description, genre, image_url]):
            return jsonify({"error": "Name, description, image_url and genre are required"}), 400

        if Artist.query.filter_by(name=name).first():
            return jsonify({"error": "Concert already exists"}), 400

        artist = Artist(
            name=name,
            description=description,
            genre=genre,
            image_url=image_url
        )

        concert.artists.append(artist)  # Связываем артиста с концертом
        db.session.add(artist)
        db.session.commit()

        return jsonify({
            "message": "Artist added successfully",
            "artist": {
                "id": artist.id,
                "name": artist.name
            }
        }), 201

    @app.route('/api/admin/statistics', methods=['GET'])
    @admin_required
    def get_statistics():
        total_revenue = db.session.query(db.func.sum(Booking.quantity * TicketType.price)) \
            .join(TicketType, Booking.ticket_type_id == TicketType.id) \
            .scalar() or 0

        total_tickets_sold = db.session.query(db.func.sum(Booking.quantity)).scalar() or 0

        active_concerts_count = Concert.query.filter(Concert.date >= datetime.utcnow()).count()

        total_bookings = Booking.query.count()
        average_booking_value = total_revenue / total_bookings if total_bookings > 0 else 0

        return jsonify({
            "total_revenue": float(total_revenue),
            "total_tickets_sold": int(total_tickets_sold),
            "active_concerts_count": active_concerts_count,
            "average_booking_value": float(average_booking_value)
        })
    
    @app.route('/api/artists', methods=['GET'])
    def list_artists():
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
    
    @app.route('/api/my-bookings', methods=['GET'])
    @jwt_required()
    def get_my_bookings():
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


    @app.route('/api/bookings', methods=['POST'])
    @jwt_required()
    def create_booking():
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

        # Проверяем доступное количество билетов
        booked_quantity = sum(b.quantity for b in ticket_type.bookings)
        available_quantity = ticket_type.total_quantity - booked_quantity

        if quantity > available_quantity:
            return jsonify({"error": f"Not enough tickets available. Only {available_quantity} left."}), 400

        # Создаем бронирование
        user_id = get_jwt()['sub']
        booking = Booking(
            user_id=user_id,
            concert_id=concert_id,
            ticket_type_id=ticket_type_id,
            quantity=quantity
        )

        db.session.add(booking)
        db.session.commit()

        return jsonify({
            "message": "Booking created successfully",
            "booking": {
                "id": booking.id,
                "concert_id": booking.concert_id,
                "ticket_type_id": booking.ticket_type_id,
                "quantity": booking.quantity,
                "status": booking.status
            }
        }), 201


    @app.route('/api/artists/<int:artist_id>', methods=['GET'])
    def get_artist(artist_id):
        artist = Artist.query.get(artist_id)

        if not artist:
            return jsonify({"error": "Artist not found"}), 404

        concerts_data = []
        for concert in artist.concerts:
            concerts_data.append({
                "id": concert.id,
                "title": concert.title,
                "date": concert.date.strftime('%Y-%m-%d %H:%M'),
                "image_url": concert.image_url
            })

        return jsonify({
            "id": artist.id,
            "name": artist.name,
            "description": artist.description,
            "genre": artist.genre,
            "image_url": artist.image_url,
            "concerts": concerts_data
        })


    @app.route("/api/admin/upload_image", methods=["POST"])
    @admin_required
    def upload_image():
        if "image" not in request.files:
            return jsonify({"error": "No file part"}), 400

        file = request.files["image"]

        if file.filename == "":
            return jsonify({"error": "No selected file"}), 400

        if not allowed_file(file.filename):
            return jsonify({"error": "Invalid file type"}), 400

        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(save_path)

        # URL для доступа к файлу
        image_url = f"/admin/static/{filename}"

        return jsonify({"image_url": image_url}), 200

    # Раздаем статические файлы из папки uploads
    @app.route('/admin/static/<path:filename>')
    def static_files(filename):
        return flask.send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    # --- Admin Panel HTML Routes ---
    @app.route('/admin/dashboard', methods=['GET', 'POST'])
    @admin_required
    def admin_dashboard():
        if request.method == 'POST':
            title = request.form.get('title')
            description = request.form.get('description')
            date_str = request.form.get('date')
            image_url = request.form.get('image_url')
            artist_ids = request.form.getlist('artist_ids') # Получаем список ID из чекбоксов

            # Обработка загрузки файла
            if 'image' in request.files and request.files['image'].filename != '':
                file = request.files['image']
                if allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    image_url = f"/admin/static/{filename}"

            try:
                date = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                # В реальном приложении здесь было бы flash-сообщение
                return redirect(url_for('admin_dashboard')) # Просто перезагружаем, если дата неверна

            new_concert = Concert(
                title=title,
                description=description,
                date=date,
                image_url=image_url
            )

            if artist_ids:
                # artist_ids уже является списком, преобразуем в int
                artists = Artist.query.filter(Artist.id.in_([int(a_id) for a_id in artist_ids])).all()
                new_concert.artists = artists

            db.session.add(new_concert)
            db.session.commit()
            
            return redirect(url_for('admin_dashboard'))

        concerts = Concert.query.order_by(Concert.date.desc()).all()
        all_artists = Artist.query.all()
        return render_template('admin_dashboard.html', concerts=concerts, all_artists=all_artists)

    @app.route('/admin/delete-concert/<int:concert_id>', methods=['POST'])
    @admin_required
    def delete_concert_admin(concert_id):
        concert = Concert.query.get(concert_id)
        if concert:
            db.session.delete(concert)
            db.session.commit()
        return redirect(url_for('admin_dashboard'))

    @app.route('/admin/edit-concert/<int:concert_id>', methods=['GET', 'POST'])
    @admin_required
    def edit_concert_admin(concert_id):
        concert = Concert.query.get_or_404(concert_id)

        if request.method == 'POST':
            concert.title = request.form.get('title')
            concert.description = request.form.get('description')
            date_str = request.form.get('date')
            artist_ids = request.form.getlist('artist_ids')

            # Обработка загрузки файла
            if 'image' in request.files and request.files['image'].filename != '':
                file = request.files['image']
                if allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    concert.image_url = f"/admin/static/{filename}"
            else:
                # Если новый файл не загружен, используем URL из формы
                concert.image_url = request.form.get('image_url')

            try:
                concert.date = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                pass # Оставляем старую дату, если формат неверный

            # Обновляем артистов
            if artist_ids:
                artists = Artist.query.filter(Artist.id.in_([int(a_id) for a_id in artist_ids])).all()
                concert.artists = artists
            else:
                concert.artists = []

            db.session.commit()
            return redirect(url_for('admin_dashboard'))

        all_artists = Artist.query.all()
        return render_template('edit_concert.html', concert=concert, all_artists=all_artists)

    @app.route('/admin/artists', methods=['GET', 'POST'])
    @admin_required
    def manage_artists():
        if request.method == 'POST':
            name = request.form.get('name')
            description = request.form.get('description')
            genre = request.form.get('genre')
            image_url = None

            if 'image' in request.files and request.files['image'].filename != '':
                file = request.files['image']
                if allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    image_url = f"/admin/static/{filename}"

            new_artist = Artist(
                name=name,
                description=description,
                genre=genre,
                image_url=image_url
            )
            db.session.add(new_artist)
            db.session.commit()
            return redirect(url_for('manage_artists'))

        artists = Artist.query.all()
        return render_template('artists.html', artists=artists)

    @app.route('/admin/edit-artist/<int:artist_id>', methods=['GET', 'POST'])
    @admin_required
    def edit_artist_admin(artist_id):
        artist = Artist.query.get_or_404(artist_id)
        if request.method == 'POST':
            artist.name = request.form.get('name')
            artist.description = request.form.get('description')
            artist.genre = request.form.get('genre')

            if 'image' in request.files and request.files['image'].filename != '':
                file = request.files['image']
                if allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    artist.image_url = f"/admin/static/{filename}"
            
            db.session.commit()
            return redirect(url_for('manage_artists'))

        return render_template('edit_artist.html', artist=artist)

    @app.route('/admin/delete-artist/<int:artist_id>', methods=['POST'])
    @admin_required
    def delete_artist_admin(artist_id):
        artist = Artist.query.get_or_404(artist_id)
        db.session.delete(artist)
        db.session.commit()
        return redirect(url_for('manage_artists'))

    @app.route('/admin/bookings')
    @admin_required
    def manage_bookings():
        bookings = Booking.query.order_by(Booking.created_at.desc()).all()
        return render_template('bookings.html', bookings=bookings)

    @app.route('/admin/manage-tickets/<int:concert_id>', methods=['GET', 'POST'])
    @admin_required
    def manage_tickets(concert_id):
        concert = Concert.query.get_or_404(concert_id)
        if request.method == 'POST':
            ticket_type = request.form.get('type')
            price = request.form.get('price')
            total_quantity = request.form.get('total_quantity')

            if ticket_type and price and total_quantity:
                new_ticket = TicketType(
                    concert_id=concert.id,
                    type=ticket_type,
                    price=float(price),
                    total_quantity=int(total_quantity)
                )
                db.session.add(new_ticket)
                db.session.commit()
            return redirect(url_for('manage_tickets', concert_id=concert.id))
        
        return render_template('manage_tickets.html', concert=concert)

    @app.route('/admin/delete-ticket/<int:ticket_id>', methods=['POST'])
    @admin_required
    def delete_ticket_type(ticket_id):
        ticket = TicketType.query.get_or_404(ticket_id)
        concert_id = ticket.concert_id
        db.session.delete(ticket)
        db.session.commit()
        return redirect(url_for('manage_tickets', concert_id=concert_id))

    return app


def run_consumer():
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
                        token = message.get('token')
                        payload_data = message.get('payload')

                        # Декодируем токен, чтобы получить user_id
                        decoded_token = decode_token(token)
                        user_id = decoded_token['sub']

                        concert_id = payload_data.get('concert_id')
                        ticket_type_id = payload_data.get('ticket_type_id')
                        quantity = payload_data.get('quantity')

                        ticket_type = TicketType.query.get(ticket_type_id)
                        if not ticket_type or ticket_type.concert_id != concert_id:
                            print(f"[Consumer] Ticket type not found for this concert")
                            ch.basic_ack(delivery_tag=method.delivery_tag)
                            return

                        booked_quantity = sum(b.quantity for b in ticket_type.bookings)
                        available_quantity = ticket_type.total_quantity - booked_quantity

                        if quantity > available_quantity:
                            print(f"[Consumer] Not enough tickets available.")
                            ch.basic_ack(delivery_tag=method.delivery_tag)
                            return

                        booking = Booking(
                            user_id=user_id,
                            concert_id=concert_id,
                            ticket_type_id=ticket_type_id,
                            quantity=quantity
                        )
                        db.session.add(booking)
                        db.session.commit()
                        print(f"[Consumer] Booking created successfully for user {user_id}")

                    except Exception as e:
                        print(f"[Consumer] Error processing message: {e}")
                        # Здесь можно добавить логику для отправки сообщения в очередь "мертвых писем"

                    ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue='booking_queue', on_message_callback=callback)
            print('[Consumer] Waiting for messages. To exit press CTRL+C')
            channel.start_consuming()

        except pika.exceptions.AMQPConnectionError as e:
            print(f"[Consumer] Connection failed, retrying in 5 seconds: {e}")
            time.sleep(5)

if __name__ == "__main__":
    app = create_app()
    consumer_thread = threading.Thread(target=run_consumer, daemon=True)
    consumer_thread.start()
    app.run(host="0.0.0.0", port=5003, debug=False) # debug=False, чтобы избежать запуска двух consumer'ов
