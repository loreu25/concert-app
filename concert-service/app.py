from flask import Flask, jsonify, request
import requests

from config import Config

ADMIN_URL = "http://admin-service:5003"

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

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