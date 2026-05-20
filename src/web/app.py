import os
import re
import base64
import types
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, redirect, url_for, request, abort, jsonify, Response, make_response, session, g
from sqlalchemy import text
from models import db, User, Deck, DeckShare, Card, Tag, StudySet, CardProgress, ReviewLog, DbState
from srs import sm2, quality_from_result, familiarity_label

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"postgresql://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
    f"@{os.environ['DB_HOST']}:{os.environ.get('DB_PORT', '5432')}/{os.environ['DB_NAME']}"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')

db.init_app(app)

@db.event.listens_for(db.session, 'before_commit')
def _mark_db_modified(session):
    if session.new or session.dirty or session.deleted:
        session.execute(text("UPDATE db_state SET last_modified = NOW() WHERE id = 1"))

_last_interaction = None
_last_interaction_lock = threading.Lock()

@app.after_request
def _record_interaction(response):
    global _last_interaction
    if request.endpoint != 'last_interaction':
        with _last_interaction_lock:
            _last_interaction = datetime.utcnow()
    return response

@app.route('/internal/last-interaction')
def last_interaction():
    with _last_interaction_lock:
        ts = _last_interaction
    if ts is None:
        return '999999'
    return str(int((datetime.utcnow() - ts).total_seconds()))

_SINGLE_USER_EMAIL = os.environ.get('SINGLE_USER', '')
_single_user_id    = None   # cached after first lookup

from authlib.integrations.flask_client import OAuth
oauth  = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

_PUBLIC_ENDPOINTS = {'login', 'auth_google', 'auth_google_callback', 'last_interaction', 'static'}

@app.before_request
def _load_user():
    global _single_user_id
    g.current_user = None

    if _SINGLE_USER_EMAIL:
        if _single_user_id is None:
            user = User.query.filter_by(email=_SINGLE_USER_EMAIL).first()
            if not user:
                user = User(email=_SINGLE_USER_EMAIL, name=_SINGLE_USER_EMAIL,
                            created_at=datetime.utcnow())
                db.session.add(user)
                db.session.commit()
            _single_user_id = user.id
        g.current_user = db.session.get(User, _single_user_id)
        return

    user_id = session.get('user_id')
    if user_id:
        g.current_user = db.session.get(User, user_id)
    if g.current_user is None and request.endpoint not in _PUBLIC_ENDPOINTS:
        return redirect(url_for('login'))

@app.context_processor
def _inject_globals():
    return dict(single_user_mode=bool(_SINGLE_USER_EMAIL))

_ACCESS_LEVELS = {None: 0, 'view': 1, 'modify': 2, 'owner': 3}

def _deck_access(deck, user):
    if deck.user_id == user.id:
        return 'owner'
    share = DeckShare.query.filter_by(deck_id=deck.id, user_id=user.id).first()
    if share:
        return 'modify' if share.can_modify else 'view'
    if deck.sharing_mode == 'public':
        return 'view'
    return None

def _require_access(deck, min_level):
    access = _deck_access(deck, g.current_user)
    if _ACCESS_LEVELS.get(access, 0) < _ACCESS_LEVELS[min_level]:
        abort(403)
    return access

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/auth/google')
def auth_google():
    return google.authorize_redirect(url_for('auth_google_callback', _external=True))

@app.route('/auth/google/callback')
def auth_google_callback():
    token = google.authorize_access_token()
    info  = token['userinfo']
    user  = User.query.filter_by(email=info['email']).first()
    if not user:
        user = User(email=info['email'], name=info['name'],
                    avatar_url=info.get('picture'), created_at=datetime.utcnow())
        db.session.add(user)
        db.session.commit()
    session['user_id'] = user.id
    return redirect(url_for('decks'))

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# Definite articles by (gender, is_plural) for each language family.
_ARTICLES = {
    'pt': {
        ('masculine', False): 'o',
        ('feminine',  False): 'a',
        ('masculine', True):  'os',
        ('feminine',  True):  'as',
    },
}


def audio_status(card_id):
    """Return (has_expression_audio, has_example_audio) without loading audio bytes."""
    from sqlalchemy import text
    row = db.session.execute(
        text('SELECT expression_audio IS NOT NULL, example_audio IS NOT NULL '
             'FROM cards WHERE id = :id'),
        {'id': card_id}
    ).first()
    return (bool(row[0]), bool(row[1])) if row else (False, False)


def get_article(noun_gender, noun_is_plural, language):
    """Return the definite article for a noun, or None if unknown.
    For 'both' gender, returns the masculine article (used for audio)."""
    lang = language.split('-')[0].lower()
    table = _ARTICLES.get(lang, {})
    gender = 'masculine' if noun_gender == 'both' else noun_gender
    return table.get((gender, bool(noun_is_plural)))


def expected_answer(card, target_language):
    """Return the full correct answer, prepending the article for nouns."""
    if card.part_of_speech == 'noun' and card.noun_gender:
        article = get_article(card.noun_gender, card.noun_is_plural, target_language)
        if article:
            return f"{article} {card.target_expression}"
    return card.target_expression


def _clean_expression(value):
    return ' '.join(value.split())


def _safe_return_url(url, fallback):
    """Validate that a return URL is a local path to prevent open redirect."""
    if url and url.startswith('/') and not url.startswith('//'):
        return url
    return fallback


def _record_review(user, card, typed_answer, quality, response_time_ms):
    """Record a review log entry and update card_progress. Returns the updated CardProgress."""
    now = datetime.utcnow()
    db.session.add(ReviewLog(
        user_id=user.id, card_id=card.id,
        typed_answer=typed_answer, quality_score=quality,
        response_time_ms=response_time_ms, was_overridden=False,
        reviewed_at=now,
    ))
    progress = CardProgress.query.filter_by(user_id=user.id, card_id=card.id).first()
    if progress is None:
        progress = CardProgress(
            user_id=user.id, card_id=card.id,
            ease_factor=2.5, interval_days=1, repetitions=0,
            next_review_at=now, created_at=now, updated_at=now,
        )
        db.session.add(progress)
    new_ef, new_interval, new_reps = sm2(
        progress.ease_factor, progress.interval_days, progress.repetitions, quality
    )
    progress.ease_factor      = new_ef
    progress.interval_days    = new_interval
    progress.repetitions      = new_reps
    progress.next_review_at   = now + timedelta(days=new_interval)
    progress.last_reviewed_at = now
    progress.updated_at       = now
    db.session.commit()
    return progress


def _do_quiz_check(deck, card, action, answer, check_url, next_url, return_url, user=None, response_time_ms=0):
    """Shared quiz answer-checking logic for deck and study-set quiz routes."""
    if action == 'flip':
        has_expr, has_ex = audio_status(card.id)
        progress = None
        if user:
            quality  = quality_from_result(correct=False, was_flipped=True, response_time_ms=response_time_ms)
            progress = _record_review(user, card, typed_answer='', quality=quality,
                                      response_time_ms=response_time_ms)
        return render_template('quiz.html', deck=deck, card=card, state='back',
                               answer=None, correct=None,
                               full_answer=expected_answer(card, deck.target_language),
                               has_expression_audio=has_expr, has_example_audio=has_ex,
                               audio_pause_ms=int(os.environ.get('CARD_FLIP_INTER_AUDIO_PAUSE_MS', '1500')),
                               check_url=check_url, next_url=next_url, return_url=return_url,
                               progress=progress,
                               familiarity=familiarity_label(progress.repetitions) if progress else None)

    # For nouns: check whether the user omitted the article entirely.
    if card.part_of_speech == 'noun' and card.noun_gender:
        article = get_article(card.noun_gender, card.noun_is_plural, deck.target_language)
        if article and answer.lower().split() == card.target_expression.lower().split():
            return render_template('quiz.html', deck=deck, card=card,
                                   state='needs_article', answer=answer,
                                   expected_article=article,
                                   check_url=check_url, next_url=next_url, return_url=return_url)

    full = expected_answer(card, deck.target_language)
    if card.part_of_speech == 'noun' and card.noun_gender == 'both':
        lang = deck.target_language
        fem_article = get_article('feminine', card.noun_is_plural, lang)
        fem_full = f"{fem_article} {card.target_expression}" if fem_article else None
        correct = answer.lower() == full.lower() or (fem_full is not None and answer.lower() == fem_full.lower())
    else:
        correct = answer.lower() == full.lower()

    progress = None
    if user:
        quality  = quality_from_result(correct=correct, was_flipped=False,
                                       response_time_ms=response_time_ms)
        progress = _record_review(user, card, typed_answer=answer, quality=quality,
                                  response_time_ms=response_time_ms)

    has_expr, has_ex = audio_status(card.id)
    return render_template('quiz.html', deck=deck, card=card, state='back',
                           answer=answer, correct=correct, full_answer=full,
                           has_expression_audio=has_expr, has_example_audio=has_ex,
                           audio_pause_ms=int(os.environ.get('AUDIO_PAUSE_MS', '1500')),
                           check_url=check_url, next_url=next_url, return_url=return_url,
                           progress=progress,
                           familiarity=familiarity_label(progress.repetitions) if progress else None)


@app.route('/')
def index():
    return redirect(url_for('decks'))


@app.route('/decks')
def decks():
    user = g.current_user
    owned = Deck.query.filter_by(user_id=user.id).all()
    shared_ids = [s.deck_id for s in DeckShare.query.filter_by(user_id=user.id).all()]
    shared = Deck.query.filter(Deck.id.in_(shared_ids)).all() if shared_ids else []
    deck_share_names = {}
    if owned:
        rows = (DeckShare.query
                .filter(DeckShare.deck_id.in_([d.id for d in owned]))
                .join(User, User.id == DeckShare.user_id)
                .add_columns(User.name)
                .all())
        for share, name in rows:
            deck_share_names.setdefault(share.deck_id, []).append(name)
    return render_template('decks.html', decks=owned, shared_decks=shared,
                           user=user, deck_share_names=deck_share_names)


@app.route('/deck/<int:deck_id>')
def deck_detail(deck_id):
    from query_parser import build_filter, QueryParseError
    user        = g.current_user
    deck        = Deck.query.get_or_404(deck_id)
    deck_access = _require_access(deck, 'view')
    study_sets  = StudySet.query.filter_by(deck_id=deck_id, user_id=user.id).order_by(StudySet.name).all()
    card_count = Card.query.filter_by(deck_id=deck_id).count()

    progress_rows = db.session.execute(
        text('SELECT cp.card_id, cp.repetitions FROM card_progress cp '
             'JOIN cards c ON c.id = cp.card_id '
             'WHERE c.deck_id = :did AND cp.user_id = :uid'),
        {'did': deck_id, 'uid': user.id}
    ).fetchall()
    progress_by_card = {row[0]: row[1] for row in progress_rows}

    def card_stats(card_ids):
        total = len(card_ids)
        if not total:
            return None
        counts = {'Unlearned': 0, 'Learning': 0, 'Familiar': 0, 'Known': 0}
        for cid in card_ids:
            counts[familiarity_label(progress_by_card.get(cid) or 0)] += 1
        pcts = {k: round(v * 100 / total) for k, v in counts.items()}
        return {'total': total, 'pcts': pcts}

    all_ids = [r[0] for r in db.session.execute(
        text('SELECT id FROM cards WHERE deck_id = :did'), {'did': deck_id}
    ).fetchall()]
    all_cards_stats = card_stats(all_ids)

    study_set_counts = {}
    study_set_stats  = {}
    for ss in study_sets:
        try:
            filt = build_filter(ss.tag_query, deck_id)
            ids  = [r[0] for r in Card.query.filter_by(deck_id=deck_id)
                                             .filter(filt)
                                             .with_entities(Card.id).all()]
            study_set_counts[ss.id] = len(ids)
            study_set_stats[ss.id]  = card_stats(ids)
        except QueryParseError:
            study_set_counts[ss.id] = None
            study_set_stats[ss.id]  = None

    deck_owner  = db.session.get(User, deck.user_id)
    share_users = []
    if deck_access == 'owner':
        for s in DeckShare.query.filter_by(deck_id=deck_id).all():
            u = db.session.get(User, s.user_id)
            if u:
                share_users.append({'share': s, 'user': u})
    share_error = request.args.get('share_error')
    share_email = request.args.get('share_email', '')

    return render_template('deck.html', deck=deck, study_sets=study_sets,
                           card_count=card_count, study_set_counts=study_set_counts,
                           study_set_stats=study_set_stats, all_cards_stats=all_cards_stats,
                           deck_access=deck_access, deck_owner=deck_owner,
                           share_users=share_users, share_error=share_error, share_email=share_email)


@app.route('/deck/<int:deck_id>/study-sets/new', methods=['GET', 'POST'])
def new_study_set(deck_id):
    from query_parser import parse, QueryParseError
    deck = Deck.query.get_or_404(deck_id)
    _require_access(deck, 'view')

    if request.method == 'POST':
        name  = request.form.get('name', '').strip()
        query = request.form.get('tag_query', '').strip()
        error = None
        if not name:
            error = 'Name is required.'
        elif not query:
            error = 'Query is required.'
        else:
            try:
                parse(query)
            except QueryParseError as e:
                error = f'Invalid query: {e}'
        if error:
            return render_template('study_set_edit.html', deck=deck, study_set=None,
                                   error=error)
        now = datetime.utcnow()
        ss  = StudySet(deck_id=deck_id, user_id=g.current_user.id, name=name, tag_query=query,
                       created_at=now, updated_at=now)
        db.session.add(ss)
        db.session.commit()
        return redirect(url_for('deck_detail', deck_id=deck_id))

    return render_template('study_set_edit.html', deck=deck, study_set=None, error=None)


@app.route('/study-set/<int:set_id>/edit', methods=['GET', 'POST'])
def edit_study_set(set_id):
    from query_parser import parse, QueryParseError
    study_set = StudySet.query.get_or_404(set_id)
    deck      = Deck.query.get_or_404(study_set.deck_id)
    _require_access(deck, 'view')
    if study_set.user_id != g.current_user.id:
        abort(403)

    if request.method == 'POST':
        name  = request.form.get('name', '').strip()
        query = request.form.get('tag_query', '').strip()
        error = None
        if not name:
            error = 'Name is required.'
        elif not query:
            error = 'Query is required.'
        else:
            try:
                parse(query)
            except QueryParseError as e:
                error = f'Invalid query: {e}'
        if error:
            return render_template('study_set_edit.html', deck=deck, study_set=study_set,
                                   error=error)
        study_set.name       = name
        study_set.tag_query      = query
        study_set.updated_at = datetime.utcnow()
        db.session.commit()
        return redirect(url_for('deck_detail', deck_id=deck.id))

    return render_template('study_set_edit.html', deck=deck, study_set=study_set, error=None)


@app.route('/study-set/<int:set_id>/delete', methods=['POST'])
def delete_study_set(set_id):
    study_set = StudySet.query.get_or_404(set_id)
    deck      = Deck.query.get_or_404(study_set.deck_id)
    _require_access(deck, 'view')
    if study_set.user_id != g.current_user.id:
        abort(403)
    deck_id   = study_set.deck_id
    db.session.delete(study_set)
    db.session.commit()
    return redirect(url_for('deck_detail', deck_id=deck_id))


@app.route('/study-set/<int:set_id>/quiz')
def study_set_quiz(set_id):
    from query_parser import build_filter, QueryParseError
    user      = g.current_user
    study_set = StudySet.query.get_or_404(set_id)
    deck      = Deck.query.get_or_404(study_set.deck_id)
    _require_access(deck, 'view')
    try:
        filt = build_filter(study_set.tag_query, deck.id)
        card = (Card.query
                .outerjoin(CardProgress, db.and_(
                    CardProgress.card_id == Card.id,
                    CardProgress.user_id == user.id,
                ))
                .filter(Card.deck_id == deck.id)
                .filter(filt)
                .order_by(text("COALESCE(card_progress.next_review_at, '1970-01-01'::timestamp) ASC"))
                .first_or_404())
    except QueryParseError:
        abort(400)
    check_url  = url_for('study_set_check', set_id=set_id)
    next_url   = url_for('study_set_quiz',  set_id=set_id)
    return_url = url_for('study_set_quiz',  set_id=set_id)
    resp = make_response(render_template('quiz.html', deck=deck, card=card, state='front',
                                        check_url=check_url, next_url=next_url, return_url=return_url))
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route('/study-set/<int:set_id>/check', methods=['POST'])
def study_set_check(set_id):
    user      = g.current_user
    study_set = StudySet.query.get_or_404(set_id)
    deck      = Deck.query.get_or_404(study_set.deck_id)
    _require_access(deck, 'view')
    card      = Card.query.get_or_404(int(request.form['card_id']))
    action    = request.form.get('action')
    answer    = request.form.get('answer', '').strip()
    response_time_ms = int(request.form.get('response_time_ms', 0))
    check_url  = url_for('study_set_check', set_id=set_id)
    next_url   = url_for('study_set_quiz',  set_id=set_id)
    return_url = url_for('study_set_quiz',  set_id=set_id)
    return _do_quiz_check(deck, card, action, answer, check_url, next_url, return_url,
                          user=user, response_time_ms=response_time_ms)


@app.route('/quiz/<int:deck_id>')
def quiz(deck_id):
    user  = g.current_user
    deck  = Deck.query.get_or_404(deck_id)
    _require_access(deck, 'view')
    card  = (Card.query
             .outerjoin(CardProgress, db.and_(
                 CardProgress.card_id == Card.id,
                 CardProgress.user_id == user.id,
             ))
             .filter(Card.deck_id == deck_id)
             .order_by(text("COALESCE(card_progress.next_review_at, '1970-01-01'::timestamp) ASC"))
             .first_or_404())
    check_url  = url_for('quiz_check', deck_id=deck_id)
    next_url   = url_for('quiz',       deck_id=deck_id)
    return_url = url_for('quiz',       deck_id=deck_id)
    resp = make_response(render_template('quiz.html', deck=deck, card=card, state='front',
                                        check_url=check_url, next_url=next_url, return_url=return_url))
    resp.headers['Cache-Control'] = 'no-store'
    return resp


PARTS_OF_SPEECH = [
    'adjective', 'adverb', 'conjunction', 'expression',
    'interjection', 'noun', 'other', 'preposition', 'pronoun', 'verb',
]

NOUN_GENDERS = [
    ('masculine',  'masculine'),
    ('feminine',   'feminine'),
    ('both',       'masculine and feminine'),
]


@app.route('/card/<int:card_id>/edit', methods=['GET', 'POST'])
def edit_card(card_id):
    card = Card.query.get_or_404(card_id)
    deck = Deck.query.get_or_404(card.deck_id)
    _require_access(deck, 'modify')
    fallback_url = url_for('quiz', deck_id=deck.id)

    if request.method == 'POST':
        new_target_expression = _clean_expression(request.form['target_expression'])
        new_target_example    = request.form.get('target_example', '').strip() or None
        expression_audio_b64  = request.form.get('expression_audio_b64', '').strip()
        example_audio_b64     = request.form.get('example_audio_b64', '').strip()

        if expression_audio_b64:
            card.expression_audio = base64.b64decode(expression_audio_b64)
        elif new_target_expression != card.target_expression:
            card.expression_audio = None

        if example_audio_b64:
            card.example_audio = base64.b64decode(example_audio_b64)
        elif new_target_example != card.target_example:
            card.example_audio = None

        card.source_expression = _clean_expression(request.form['source_expression'])
        card.source_example    = request.form.get('source_example', '').strip() or None
        card.target_expression = new_target_expression
        card.target_example    = new_target_example
        card.part_of_speech    = request.form.get('part_of_speech') or None
        card.noun_gender       = request.form.get('noun_gender') or None
        card.noun_is_plural    = 'noun_is_plural' in request.form
        card.notes             = request.form.get('notes', '').strip() or None
        db.session.commit()

        return_url = _safe_return_url(request.form.get('return_url'), fallback_url)
        return redirect(return_url)

    return_url = _safe_return_url(request.args.get('return_url'), fallback_url)
    all_tags   = Tag.query.filter_by(deck_id=card.deck_id).order_by(Tag.name).all()
    return render_template('edit_card.html', card=card, deck=deck,
                           parts_of_speech=PARTS_OF_SPEECH, noun_genders=NOUN_GENDERS,
                           has_expression_audio=card.expression_audio is not None,
                           has_example_audio=card.example_audio is not None,
                           all_tags=all_tags, return_url=return_url)


@app.route('/deck/<int:deck_id>/cards/new', methods=['GET', 'POST'])
def add_card(deck_id):
    deck = Deck.query.get_or_404(deck_id)
    _require_access(deck, 'modify')
    fallback_url = url_for('deck_detail', deck_id=deck_id)

    if request.method == 'POST':
        expression_audio_b64 = request.form.get('expression_audio_b64', '').strip()
        example_audio_b64    = request.form.get('example_audio_b64', '').strip()
        card = Card(
            deck_id=deck_id,
            source_expression=_clean_expression(request.form['source_expression']),
            source_example=request.form.get('source_example', '').strip() or None,
            target_expression=_clean_expression(request.form['target_expression']),
            target_example=request.form.get('target_example', '').strip() or None,
            part_of_speech=request.form.get('part_of_speech') or None,
            noun_gender=request.form.get('noun_gender') or None,
            noun_is_plural='noun_is_plural' in request.form,
            notes=request.form.get('notes', '').strip() or None,
            expression_audio=base64.b64decode(expression_audio_b64) if expression_audio_b64 else None,
            example_audio=base64.b64decode(example_audio_b64) if example_audio_b64 else None,
            created_by=g.current_user.id,
        )
        db.session.add(card)
        db.session.flush()
        for tag_name in request.form.getlist('tag'):
            tag_name = tag_name.strip()
            if not tag_name or any(c.isspace() for c in tag_name):
                continue
            tag = Tag.query.filter(Tag.deck_id == deck_id,
                                   db.func.lower(Tag.name) == tag_name.lower()).first()
            if not tag:
                tag = Tag(deck_id=deck_id, name=tag_name)
                db.session.add(tag)
                db.session.flush()
            card.tags.append(tag)
        db.session.commit()
        return_url = _safe_return_url(request.form.get('return_url'), fallback_url)
        return redirect(return_url)

    stub = types.SimpleNamespace(
        id=None,
        source_expression='', source_example=None,
        target_expression='', target_example=None,
        part_of_speech=None, noun_gender=None, noun_is_plural=False,
        notes=None, tags=[],
        expression_audio=None, example_audio=None,
    )
    return_url = _safe_return_url(request.args.get('return_url'), fallback_url)
    all_tags   = Tag.query.filter_by(deck_id=deck_id).order_by(Tag.name).all()
    return render_template('edit_card.html', card=stub, deck=deck,
                           parts_of_speech=PARTS_OF_SPEECH, noun_genders=NOUN_GENDERS,
                           has_expression_audio=False, has_example_audio=False,
                           all_tags=all_tags, return_url=return_url,
                           form_action=url_for('add_card', deck_id=deck_id))


@app.route('/card/<int:card_id>/quiz')
def quiz_card(card_id):
    card  = Card.query.get_or_404(card_id)
    deck  = Deck.query.get_or_404(card.deck_id)
    _require_access(deck, 'view')
    check_url  = url_for('quiz_check', deck_id=deck.id)
    next_url   = url_for('quiz',       deck_id=deck.id)
    return_url = url_for('quiz',       deck_id=deck.id)
    return render_template('quiz.html', deck=deck, card=card, state='front',
                           check_url=check_url, next_url=next_url, return_url=return_url)


@app.route('/quiz/<int:deck_id>/check', methods=['POST'])
def quiz_check(deck_id):
    user      = g.current_user
    deck      = Deck.query.get_or_404(deck_id)
    _require_access(deck, 'view')
    card      = Card.query.get_or_404(int(request.form['card_id']))
    action    = request.form.get('action')
    answer    = request.form.get('answer', '').strip()
    response_time_ms = int(request.form.get('response_time_ms', 0))
    check_url  = url_for('quiz_check', deck_id=deck_id)
    next_url   = url_for('quiz',       deck_id=deck_id)
    return_url = url_for('quiz',       deck_id=deck_id)
    return _do_quiz_check(deck, card, action, answer, check_url, next_url, return_url,
                          user=user, response_time_ms=response_time_ms)


@app.route('/deck/<int:deck_id>/words')
def deck_words(deck_id):
    from sqlalchemy.orm import joinedload
    user  = g.current_user
    deck  = Deck.query.get_or_404(deck_id)
    deck_access = _require_access(deck, 'view')
    cards = (Card.query
             .filter_by(deck_id=deck_id)
             .options(joinedload(Card.tags))
             .order_by(Card.source_expression)
             .all())
    rows = db.session.execute(
        text('SELECT id, expression_audio IS NOT NULL, example_audio IS NOT NULL FROM cards WHERE deck_id = :did'),
        {'did': deck_id}
    ).fetchall()
    audio_map = {r[0]: (bool(r[1]), bool(r[2])) for r in rows}
    card_ids  = [c.id for c in cards]
    progress_list = (CardProgress.query
                     .filter(CardProgress.user_id == user.id,
                             CardProgress.card_id.in_(card_ids))
                     .all()) if card_ids else []
    progress_map = {p.card_id: p for p in progress_list}
    all_tags  = Tag.query.filter_by(deck_id=deck_id).order_by(Tag.name).all()
    return render_template('words.html', cards=cards, deck=deck, audio_map=audio_map,
                           all_tags=all_tags, progress_map=progress_map,
                           familiarity_label=familiarity_label, deck_access=deck_access)


@app.route('/deck/<int:deck_id>/tags')
def deck_tags(deck_id):
    """Return JSON list of tag names in this deck, optionally filtered by prefix."""
    deck = Deck.query.get_or_404(deck_id)
    _require_access(deck, 'view')
    q    = request.args.get('q', '').strip().lower()
    tags = Tag.query.filter_by(deck_id=deck_id)
    if q:
        tags = tags.filter(db.func.lower(Tag.name).startswith(q))
    tags = tags.order_by(Tag.name).all()
    return jsonify(tags=[t.name for t in tags])


@app.route('/card/<int:card_id>/review/override', methods=['POST'])
def override_review(card_id):
    user = g.current_user
    card = Card.query.get_or_404(card_id)
    _require_access(Deck.query.get_or_404(card.deck_id), 'view')
    log = (ReviewLog.query
           .filter_by(user_id=user.id, card_id=card_id)
           .order_by(ReviewLog.reviewed_at.desc())
           .first())
    if log is None:
        return jsonify(error='No review found'), 404
    log.was_overridden = True
    log.quality_score  = 4
    progress = CardProgress.query.filter_by(user_id=user.id, card_id=card_id).first()
    if progress:
        now = datetime.utcnow()
        new_ef, new_interval, new_reps = sm2(
            progress.ease_factor, progress.interval_days, progress.repetitions, 4
        )
        progress.ease_factor      = new_ef
        progress.interval_days    = new_interval
        progress.repetitions      = new_reps
        progress.next_review_at   = now + timedelta(days=new_interval)
        progress.updated_at       = now
    db.session.commit()
    label = familiarity_label(progress.repetitions) if progress else 'Unlearned'
    return jsonify(familiarity=label,
                   next_review_days=progress.interval_days if progress else 1)


@app.route('/card/<int:card_id>/tags/add', methods=['POST'])
def card_tag_add(card_id):
    card = Card.query.get_or_404(card_id)
    _require_access(Deck.query.get_or_404(card.deck_id), 'modify')
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify(error='Tag name required'), 400
    if any(c.isspace() for c in name):
        return jsonify(error='Tag names may not contain whitespace'), 400

    # Find or create the tag (case-insensitive, stored as-entered on first create)
    tag = Tag.query.filter(Tag.deck_id == card.deck_id,
                           db.func.lower(Tag.name) == name.lower()).first()
    if not tag:
        tag = Tag(deck_id=card.deck_id, name=name)
        db.session.add(tag)
        db.session.flush()  # assign tag.id before checking card.tags

    existing_ids = {t.id for t in card.tags}
    if tag.id not in existing_ids:
        card.tags.append(tag)
    db.session.commit()

    return jsonify(tags=[t.name for t in card.tags])


@app.route('/card/<int:card_id>/tags/remove', methods=['POST'])
def card_tag_remove(card_id):
    card = Card.query.get_or_404(card_id)
    _require_access(Deck.query.get_or_404(card.deck_id), 'modify')
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify(error='Tag name required'), 400

    tag = Tag.query.filter(Tag.deck_id == card.deck_id,
                           db.func.lower(Tag.name) == name.lower()).first()
    if tag:
        tag_ids = {t.id for t in card.tags}
        if tag.id in tag_ids:
            card.tags.remove(tag)
            db.session.commit()

    return jsonify(tags=[t.name for t in card.tags])


@app.route('/card/<int:card_id>/suggest', methods=['POST'])
def suggest(card_id):
    try:
        from llm import suggest_sentence_pairs
        card = Card.query.get_or_404(card_id)
        deck = Deck.query.get_or_404(card.deck_id)
        _require_access(deck, 'view')

        data              = request.get_json(force=True)
        source_expression = (data.get('source_expression') or card.source_expression).strip()
        target_expression = (data.get('target_expression') or card.target_expression).strip()
        part_of_speech    = data.get('part_of_speech') or card.part_of_speech
        count             = int(os.environ.get('SUGGESTION_COUNT', '3'))

        pairs = suggest_sentence_pairs(
            source_expression, target_expression, part_of_speech, card.notes,
            deck.source_language, deck.target_language,
            count,
        )
        return jsonify(pairs=[{'source': p.source, 'target': p.target} for p in pairs])
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route('/card/<int:card_id>/translate', methods=['POST'])
def translate(card_id):
    try:
        from llm import translate_example
        card = Card.query.get_or_404(card_id)
        deck = Deck.query.get_or_404(card.deck_id)
        _require_access(deck, 'view')

        data              = request.get_json(force=True)
        source_expression = (data.get('source_expression') or card.source_expression).strip()
        target_expression = (data.get('target_expression') or card.target_expression).strip()
        source_example    = (data.get('source_example') or '').strip()
        part_of_speech    = data.get('part_of_speech') or card.part_of_speech

        if not source_example:
            return jsonify(error='No source example to translate.'), 400

        result = translate_example(
            source_expression, target_expression, source_example,
            part_of_speech, card.notes,
            deck.source_language, deck.target_language,
        )
        return jsonify(translation=result.translation, problem=result.problem)
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route('/card/<int:card_id>/audio/<field>', methods=['GET'])
def serve_audio(card_id, field):
    if field not in ('expression', 'example'):
        abort(404)
    card = Card.query.get_or_404(card_id)
    _require_access(Deck.query.get_or_404(card.deck_id), 'view')
    audio = card.expression_audio if field == 'expression' else card.example_audio
    if not audio:
        abort(404)
    return Response(audio, mimetype='audio/mpeg',
                    headers={'Cache-Control': 'no-store'})


def _with_article(text, part_of_speech, noun_gender, noun_is_plural, language):
    if part_of_speech == 'noun' and noun_gender:
        article = get_article(noun_gender, noun_is_plural, language)
        if article:
            text = f"{article} {text}"
    if not re.search(r'[.!?]\s*$', text):
        text = f"{text}."
    return text


@app.route('/card/<int:card_id>/audio/<field>/generate', methods=['POST'])
def generate_audio(card_id, field):
    if field not in ('expression', 'example'):
        abort(404)
    try:
        from tts import generate_audio as tts_generate
        card = Card.query.get_or_404(card_id)
        deck = Deck.query.get_or_404(card.deck_id)
        _require_access(deck, 'view')

        data = request.get_json(force=True)
        text = (data.get('text') or '').strip()
        if not text:
            return jsonify(error='No text to generate audio for.'), 400

        if field == 'expression':
            part_of_speech = data.get('part_of_speech') or card.part_of_speech
            noun_gender    = data.get('noun_gender')    or card.noun_gender
            noun_is_plural = data.get('noun_is_plural', card.noun_is_plural)
            text = _with_article(text, part_of_speech, noun_gender, noun_is_plural, deck.target_language)

        audio = tts_generate(text)
        return jsonify(audio_b64=base64.b64encode(audio).decode())
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route('/deck/<int:deck_id>/suggest', methods=['POST'])
def deck_suggest(deck_id):
    try:
        from llm import suggest_sentence_pairs
        deck = Deck.query.get_or_404(deck_id)
        _require_access(deck, 'view')
        data              = request.get_json(force=True)
        source_expression = (data.get('source_expression') or '').strip()
        target_expression = (data.get('target_expression') or '').strip()
        part_of_speech    = data.get('part_of_speech') or None
        count             = int(os.environ.get('SUGGESTION_COUNT', '3'))
        pairs = suggest_sentence_pairs(
            source_expression, target_expression, part_of_speech, None,
            deck.source_language, deck.target_language, count,
        )
        return jsonify(pairs=[{'source': p.source, 'target': p.target} for p in pairs])
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route('/deck/<int:deck_id>/translate', methods=['POST'])
def deck_translate(deck_id):
    try:
        from llm import translate_example
        deck = Deck.query.get_or_404(deck_id)
        _require_access(deck, 'view')
        data              = request.get_json(force=True)
        source_expression = (data.get('source_expression') or '').strip()
        target_expression = (data.get('target_expression') or '').strip()
        source_example    = (data.get('source_example') or '').strip()
        part_of_speech    = data.get('part_of_speech') or None
        if not source_example:
            return jsonify(error='No source example to translate.'), 400
        result = translate_example(
            source_expression, target_expression, source_example,
            part_of_speech, None,
            deck.source_language, deck.target_language,
        )
        return jsonify(translation=result.translation, problem=result.problem)
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route('/deck/<int:deck_id>/audio/generate', methods=['POST'])
def deck_generate_audio(deck_id):
    deck = Deck.query.get_or_404(deck_id)
    _require_access(deck, 'view')
    try:
        from tts import generate_audio as tts_generate
        data = request.get_json(force=True)
        text = (data.get('text') or '').strip()
        if not text:
            return jsonify(error='No text to generate audio for.'), 400

        if data.get('field') == 'expression':
            text = _with_article(
                text,
                data.get('part_of_speech'),
                data.get('noun_gender'),
                bool(data.get('noun_is_plural')),
                deck.target_language,
            )

        audio = tts_generate(text)
        return jsonify(audio_b64=base64.b64encode(audio).decode())
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route('/deck/<int:deck_id>/share/add', methods=['POST'])
def deck_share_add(deck_id):
    deck    = Deck.query.get_or_404(deck_id)
    _require_access(deck, 'owner')
    email   = request.form.get('email', '').strip().lower()
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def err(msg):
        if is_ajax:
            return jsonify(ok=False, error=msg)
        return redirect(url_for('deck_detail', deck_id=deck_id,
                                share_error=msg, share_email=email))

    if not email:
        return err('Email is required.')
    target = User.query.filter_by(email=email).first()
    if not target:
        return err(f'No user found with email {email}.')
    if target.id == g.current_user.id:
        return err('You cannot share a deck with yourself.')
    if DeckShare.query.filter_by(deck_id=deck_id, user_id=target.id).first():
        return err(f'{target.name} already has access to this deck.')

    db.session.add(DeckShare(deck_id=deck_id, user_id=target.id,
                             can_modify=False, created_at=datetime.utcnow()))
    db.session.commit()
    if is_ajax:
        return jsonify(ok=True, user_id=target.id, name=target.name, email=target.email)
    return redirect(url_for('deck_detail', deck_id=deck_id))


@app.route('/deck/<int:deck_id>/share/<int:user_id>/set-modify', methods=['POST'])
def deck_share_set_modify(deck_id, user_id):
    deck  = Deck.query.get_or_404(deck_id)
    _require_access(deck, 'owner')
    share = DeckShare.query.filter_by(deck_id=deck_id, user_id=user_id).first_or_404()
    share.can_modify = request.form.get('can_modify') == '1'
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(ok=True)
    return redirect(url_for('deck_detail', deck_id=deck_id))


@app.route('/deck/<int:deck_id>/share/<int:user_id>/remove', methods=['POST'])
def deck_share_remove(deck_id, user_id):
    deck  = Deck.query.get_or_404(deck_id)
    _require_access(deck, 'owner')
    share = DeckShare.query.filter_by(deck_id=deck_id, user_id=user_id).first_or_404()
    db.session.delete(share)
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(ok=True)
    return redirect(url_for('deck_detail', deck_id=deck_id))


@app.route('/deck/<int:deck_id>/set-sharing-mode', methods=['POST'])
def deck_set_sharing_mode(deck_id):
    deck = Deck.query.get_or_404(deck_id)
    _require_access(deck, 'owner')
    mode = request.form.get('sharing_mode', 'private')
    if mode not in ('private', 'shared', 'public'):
        mode = 'private'
    deck.sharing_mode = mode
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(ok=True)
    return redirect(url_for('deck_detail', deck_id=deck_id))
