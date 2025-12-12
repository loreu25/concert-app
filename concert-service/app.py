from flask import Flask, jsonify, request, render_template, redirect, url_for, flash, make_response, g
import requests
import jwt

from config import Config

ADMIN_URL = "http://admin-service:5003"
AUTH_URL = "http://auth-service:5001"

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.secret_key = 'super-secret-key-for-flash' # Необходим для flash-сообщений

    @app.before_request
    def load_user_from_cookie():
        token = request.cookies.get('access_token')
        g.user = None
        if token:
            try:
                decoded_token = jwt.decode(token, options={"verify_signature": False})
                g.user = decoded_token
            except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
                g.user = None

    # --- HTML Pages ---

    @app.route('/')
    def index():
        return redirect(url_for('list_concerts_page'))

    @app.route('/concerts-page')
    def list_concerts_page():
        try:
            response = requests.get(f"{ADMIN_URL}/concerts")
            response.raise_for_status()
            concerts = response.json()
        except requests.exceptions.RequestException:
            concerts = []
            flash('Не удалось загрузить афишу. Попробуйте позже.', 'danger')
        return render_template('index.html', concerts=concerts)

    @app.route('/concerts-page/<int:concert_id>')
    def concert_detail_page(concert_id):
        try:
            response = requests.get(f"{ADMIN_URL}/concerts/{concert_id}")
            response.raise_for_status()
            concert = response.json()
        except requests.exceptions.RequestException:
            return render_template('404.html'), 404
        return render_template('concert_detail.html', concert=concert)

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')
            response = requests.post(f"{AUTH_URL}/register", json={'email': email, 'password': password})
            if response.status_code == 201:
                flash('Вы успешно зарегистрированы! Теперь можете войти.', 'success')
                return redirect(url_for('login'))
            else:
                error = response.json().get('error', 'Ошибка регистрации.')
                flash(error, 'danger')
        return render_template('register.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')
            response = requests.post(f"{AUTH_URL}/login", json={'email': email, 'password': password})
            if response.status_code == 200:
                access_token = response.json().get('access_token')
                resp = make_response(redirect(url_for('list_concerts_page')))
                resp.set_cookie('access_token', access_token, httponly=True, samesite='Lax')
                flash('Вы успешно вошли!', 'success')
                return resp
            else:
                flash('Неверный email или пароль.', 'danger')
        return render_template('login.html')

    @app.route('/logout')
    def logout():
        resp = make_response(redirect(url_for('list_concerts_page')))
        resp.delete_cookie('access_token')
        flash('Вы вышли из аккаунта.', 'success')
        return resp

    @app.route('/create-booking/<int:concert_id>', methods=['POST'])
    def create_booking_page(concert_id):
        if not g.user:
            flash('Пожалуйста, войдите, чтобы забронировать билеты.', 'danger')
            return redirect(url_for('login'))

        ticket_type_id = request.form.get('ticket_type_id')
        quantity = request.form.get('quantity')

        token = request.cookies.get('access_token')
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        payload = {
            'concert_id': concert_id,
            'ticket_type_id': int(ticket_type_id),
            'quantity': int(quantity)
        }

        response = requests.post(f"{ADMIN_URL}/bookings", json=payload, headers=headers)

        if response.status_code == 201:
            flash('Билеты успешно забронированы!', 'success')
        else:
            error = response.json().get('error', 'Не удалось забронировать билеты.')
            flash(error, 'danger')
        
        return redirect(url_for('concert_detail_page', concert_id=concert_id))

    @app.route('/my-bookings')
    def my_bookings_page():
        if not g.user:
            flash('Пожалуйста, войдите, чтобы просмотреть свои бронирования.', 'danger')
            return redirect(url_for('login'))

        token = request.cookies.get('access_token')
        headers = {'Authorization': f'Bearer {token}'}
        
        try:
            response = requests.get(f"{ADMIN_URL}/my-bookings", headers=headers)
            response.raise_for_status()
            bookings_raw = response.json()
            
            # Обогащаем данные о бронированиях для удобного отображения
            bookings = []
            for b in bookings_raw:
                # Получаем детали концерта
                concert_resp = requests.get(f"{ADMIN_URL}/concerts/{b['concert_id']}")
                concert_title = concert_resp.json().get('title', 'Неизвестный концерт') if concert_resp.ok else 'Неизвестный концерт'
                
                # Находим тип билета в данных концерта
                ticket_type = 'Неизвестный тип'
                if concert_resp.ok:
                    for tt in concert_resp.json().get('ticket_types', []):
                        if tt['id'] == b['ticket_type_id']:
                            ticket_type = tt['type']
                            break
                
                bookings.append({
                    'id': b['id'],
                    'concert_title': concert_title,
                    'ticket_type': ticket_type,
                    'quantity': b['quantity'],
                    'status': b['status'],
                    'created_at': b['created_at']
                })

        except requests.exceptions.RequestException:
            bookings = []
            flash('Не удалось загрузить бронирования.', 'danger')

        return render_template('my_bookings.html', bookings=bookings)

    # --- JSON API Endpoints (for future use) ---

    @app.route('/concerts', methods=['GET'])
    def list_concerts():
        response = requests.get(f"{ADMIN_URL}/concerts")

        concerts = response.json()
        data = []

        for c in concerts:
            artists = c.get("artists", [])
            ticket_types = c.get("ticket_types", [])

            tickets_data = []
            for t in ticket_types:
                tickets_data.append({
                    "id": t["id"],
                    "type": t["type"],
                    "price": t["price"],
                    "total_quantity": t["total_quantity"]
                })

            data.append({
                "id": c["id"],
                "title": c["title"],
                "date": c["date"],  # admin-service уже возвращает строку
                "image": c.get("image_url"),
                "artists": artists or ["Не указан"],
                "ticket_types": tickets_data
            })
        return jsonify(data)

    @app.route('/concerts/<int:concert_id>', methods=['GET'])
    def get_concert(concert_id):
        response = requests.get(f"{ADMIN_URL}/concerts/{concert_id}")

        if response.status_code == 404:
            return jsonify({"error": "Concert not found"}), 404
        elif response.status_code != 200:
            return jsonify({"error": "Service unavailable"}), 502

        concert = response.json()

        return jsonify({
            "id": concert.get('id'),
            "title": concert.get('title'),
            "description": concert.get('description'),
            "date": concert.get('date'),
            "image_url": concert.get('image_url'),
            "artists": concert.get('artists', []),
            "ticket_types": concert.get('ticket_types', [])
        })
    
    @app.route('/artists', methods=['GET'])
    def get_artists():
        response = requests.get(f"{ADMIN_URL}/artists")

        if response.status_code == 404:
            return jsonify({"error": "Artist not found"}), 404
        elif response.status_code != 200:
            return jsonify({"error": "Service unavailable"}), 502
        
        artists = response.json()
        data = []

        for a in artists:
            data.append({
                "id": a["id"],
                "name": a["name"],
                "description": a["description"],
                "genre": a["genre"],
                "image_url": a["image_url"]
            })
        return jsonify(data)
    
    @app.route('/my-bookings', methods=['GET'])
    def get_my_bookings():
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"error": "Authorization header is missing"}), 401

        headers = {'Authorization': auth_header}
        response = requests.get(f"{ADMIN_URL}/my-bookings", headers=headers)

        return jsonify(response.json()), response.status_code
    
    @app.route('/bookings', methods=['POST'])
    def create_booking():
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"error": "Authorization header is missing"}), 401

        headers = {'Authorization': auth_header, 'Content-Type': 'application/json'}
        response = requests.post(f"{ADMIN_URL}/bookings", json=request.json, headers=headers)

        return jsonify(response.json()), response.status_code
    
    @app.route('/artists/<int:artist_id>', methods=['GET'])
    def get_artist(artist_id):
        response = requests.get(f"{ADMIN_URL}/artists/{artist_id}")

        if response.status_code == 404:
            return jsonify({"error": "Artist not found"}), 404
        elif response.status_code != 200:
            return jsonify({"error": "Service unavailable"}), 502

        artist = response.json()

        return jsonify({
            "id": artist.get('id'),
            "name": artist.get('name'),
            "description": artist.get('description'),
            "genre": artist.get('genre'),
            "image_url": artist.get('image_url'),
            "concerts": artist.get('concerts', [])  
        })

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5002, debug=True)