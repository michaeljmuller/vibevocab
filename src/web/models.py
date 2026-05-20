from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import deferred

db = SQLAlchemy()

# Association table for Card <-> Tag many-to-many
card_tags = db.Table('card_tags',
    db.Column('card_id', db.Integer, db.ForeignKey('cards.id'), primary_key=True),
    db.Column('tag_id',  db.Integer, db.ForeignKey('tags.id'),  primary_key=True)
)


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
    id                = db.Column(db.Integer, primary_key=True)
    user_id           = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name              = db.Column(db.Text, nullable=False)
    source_language   = db.Column(db.Text, nullable=False)
    target_language   = db.Column(db.Text, nullable=False)
    sharing_mode      = db.Column(db.Text, nullable=False, default='private')
    tts_voice_id      = db.Column(db.Text)
    tts_speed         = db.Column(db.Float, nullable=False, default=1.0)
    tts_stability     = db.Column(db.Float, nullable=False, default=0.48)
    tts_similarity    = db.Column(db.Float, nullable=False, default=0.75)
    tts_style         = db.Column(db.Float, nullable=False, default=0.08)
    tts_speaker_boost = db.Column(db.Boolean, nullable=False, default=True)
    created_at        = db.Column(db.DateTime, nullable=False)
    updated_at        = db.Column(db.DateTime, nullable=False)


class DeckShare(db.Model):
    __tablename__ = 'deck_shares'
    deck_id    = db.Column(db.Integer, db.ForeignKey('decks.id', ondelete='CASCADE'), primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    can_modify = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Tag(db.Model):
    __tablename__ = 'tags'
    id      = db.Column(db.Integer, primary_key=True)
    deck_id = db.Column(db.Integer, db.ForeignKey('decks.id'), nullable=False)
    name    = db.Column(db.Text, nullable=False)
    # Uniqueness enforced case-insensitively by ix_tags_deck_id_name index in the DB


class StudySet(db.Model):
    __tablename__ = 'study_sets'
    id         = db.Column(db.Integer, primary_key=True)
    deck_id    = db.Column(db.Integer, db.ForeignKey('decks.id'), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name       = db.Column(db.Text, nullable=False)
    tag_query  = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False)


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
    created_by        = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at        = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at        = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    tags              = db.relationship('Tag', secondary=card_tags, lazy='select')


class CardProgress(db.Model):
    __tablename__ = 'card_progress'
    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    card_id          = db.Column(db.Integer, db.ForeignKey('cards.id'), nullable=False)
    ease_factor      = db.Column(db.Float, nullable=False, default=2.5)
    interval_days    = db.Column(db.Integer, nullable=False, default=1)
    repetitions      = db.Column(db.Integer, nullable=False, default=0)
    next_review_at   = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_reviewed_at = db.Column(db.DateTime)
    created_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class DbState(db.Model):
    __tablename__ = 'db_state'
    id             = db.Column(db.Integer, primary_key=True)
    last_modified  = db.Column(db.DateTime(timezone=True), nullable=False)
    last_backup_at = db.Column(db.DateTime(timezone=True))


class ElevenLabsVoice(db.Model):
    __tablename__ = 'elevenlabs_voices'
    voice_id    = db.Column(db.Text, primary_key=True)
    name        = db.Column(db.Text, nullable=False)
    language    = db.Column(db.Text)
    locale      = db.Column(db.Text)
    gender      = db.Column(db.Text)
    age         = db.Column(db.Text)
    accent      = db.Column(db.Text)
    use_case    = db.Column(db.Text)
    descriptive = db.Column(db.Text)
    preview_url = db.Column(db.Text)
    cached_at   = db.Column(db.DateTime, nullable=False)


class ReviewLog(db.Model):
    __tablename__ = 'review_log'
    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    card_id          = db.Column(db.Integer, db.ForeignKey('cards.id'), nullable=False)
    typed_answer     = db.Column(db.Text, nullable=False)
    quality_score    = db.Column(db.Integer, nullable=False)
    response_time_ms = db.Column(db.Integer, nullable=False)
    was_overridden   = db.Column(db.Boolean, nullable=False, default=False)
    reviewed_at      = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
