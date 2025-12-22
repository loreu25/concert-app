from flask import Flask, jsonify, request
import requests
from flasgger import Swagger

from config import Config

ADMIN_URL = "http://admin-service:5003"

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
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
                  image:
                    type: string
                  artists:
                    type: array
                    items:
                      type: string
                  ticket_types:
                    type: array
        """
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
                "date": c["date"],
                "image": c.get("image_url"),
                "artists": artists or ["Не указан"],
                "ticket_types": tickets_data
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
          502:
            description: Сервис недоступен
        """
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
        """
        Получить список всех артистов
        ---
        tags:
          - Artists
        responses:
          200:
            description: Список всех артистов
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
          404:
            description: Артисты не найдены
          502:
            description: Сервис недоступен
        """
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
                    type: integer
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
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"error": "Authorization header is missing"}), 401

        headers = {'Authorization': auth_header}
        response = requests.get(f"{ADMIN_URL}/my-bookings", headers=headers)

        return jsonify(response.json()), response.status_code
    
    @app.route('/bookings', methods=['POST'])
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
            description: Бронирование успешно создано
            schema:
              type: object
              properties:
                message:
                  type: string
                booking:
                  type: object
          400:
            description: Ошибка валидации
          401:
            description: Требуется аутентификация
          404:
            description: Концерт или тип билета не найден
        """
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"error": "Authorization header is missing"}), 401

        headers = {'Authorization': auth_header, 'Content-Type': 'application/json'}
        response = requests.post(f"{ADMIN_URL}/bookings", json=request.json, headers=headers)

        return jsonify(response.json()), response.status_code
    
    @app.route('/artists/<int:artist_id>', methods=['GET'])
    def get_artist(artist_id):
        """
        Получить информацию об артисте
        ---
        tags:
          - Artists
        parameters:
          - in: path
            name: artist_id
            type: integer
            required: true
            description: ID артиста
        responses:
          200:
            description: Информация об артисте
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
                concerts:
                  type: array
          404:
            description: Артист не найден
          502:
            description: Сервис недоступен
        """
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