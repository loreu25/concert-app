from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Artist(db.Model):
    __tablename__ = 'artists'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    genre = db.Column(db.String(50))
    image_url = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Многие-ко-многим с концертами
    concerts = db.relationship('Concert', secondary='concert_artists', back_populates='artists')

    def __repr__(self):
        return f'<Artist {self.name}>'


# ==================== CONCERTS ====================
class Concert(db.Model):
    __tablename__ = 'concerts'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    date = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    image_url = db.Column(db.String(500))

    # Связи
    artists = db.relationship('Artist', secondary='concert_artists', back_populates='concerts')
    ticket_types = db.relationship('TicketType', back_populates='concert', cascade='all, delete-orphan')
    bookings = db.relationship('Booking', back_populates='concert', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Concert {self.title} — {self.date.strftime("%d.%m.%Y %H:%M")}>'


# ==================== Связующая таблица concert_artists ====================
concert_artists = db.Table(
    'concert_artists',
    db.Column('concert_id', db.Integer, db.ForeignKey('concerts.id'), primary_key=True),
    db.Column('artist_id', db.Integer, db.ForeignKey('artists.id'), primary_key=True)
)


# ==================== TICKET TYPES ====================
class TicketType(db.Model):
    __tablename__ = 'ticket_types'

    id = db.Column(db.Integer, primary_key=True)
    concert_id = db.Column(db.Integer, db.ForeignKey('concerts.id'), nullable=False)
    type = db.Column(db.String(50), nullable=False)        # например: "VIP", "Стандарт", "Партер"
    price = db.Column(db.Numeric(10, 2), nullable=False)
    total_quantity = db.Column(db.Integer, nullable=False)
    

    concert = db.relationship('Concert', back_populates='ticket_types')
    bookings = db.relationship('Booking', back_populates='ticket_type')

    def __repr__(self):
        return f'<TicketType {self.type} — {self.price} руб.>'


# ==================== BOOKINGS ====================
class Booking(db.Model):
    __tablename__ = 'bookings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    concert_id = db.Column(db.Integer, db.ForeignKey('concerts.id'), nullable=False)
    ticket_type_id = db.Column(db.Integer, db.ForeignKey('ticket_types.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='booked')  # booked, paid, cancelled
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Связи
    concert = db.relationship('Concert', back_populates='bookings')
    ticket_type = db.relationship('TicketType', back_populates='bookings')

    def __repr__(self):
        return f'<Booking #{self.id} | {self.quantity} бил. на концерт {self.concert_id}>'
