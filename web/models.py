from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import deferred

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'
    id         = db.Column(db.Integer, primary_key=True)
    email      = db.Column(db.Text, nullable=False, unique=True)
    name       = db.Column(db.Text, nullable=False)
    avatar_url = db.Column(db.Text)
    is_admin   = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False)


class Deck(db.Model):
    __tablename__ = 'decks'
    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name            = db.Column(db.Text, nullable=False)
    source_language = db.Column(db.Text, nullable=False)
    target_language = db.Column(db.Text, nullable=False)
    created_at      = db.Column(db.DateTime, nullable=False)
    updated_at      = db.Column(db.DateTime, nullable=False)


class Card(db.Model):
    __tablename__ = 'cards'
    id                = db.Column(db.Integer, primary_key=True)
    deck_id           = db.Column(db.Integer, db.ForeignKey('decks.id'), nullable=False)
    source_expression = db.Column(db.Text, nullable=False)
    source_example    = db.Column(db.Text)
    target_expression = db.Column(db.Text, nullable=False)
    target_example    = db.Column(db.Text)
    part_of_speech    = db.Column(db.Text)
    noun_gender       = db.Column(db.Text)
    noun_is_plural    = db.Column(db.Boolean, nullable=False, default=False)
    notes             = db.Column(db.Text)
    expression_audio  = deferred(db.Column(db.LargeBinary))
    example_audio     = deferred(db.Column(db.LargeBinary))
    created_at        = db.Column(db.DateTime, nullable=False)
    updated_at        = db.Column(db.DateTime, nullable=False)
