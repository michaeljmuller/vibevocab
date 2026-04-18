import os
import base64
import types
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, request, abort, jsonify, Response, make_response
from models import db, User, Deck, Card, Tag, StudySet

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"postgresql://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
    f"@{os.environ['DB_HOST']}:{os.environ.get('DB_PORT', '5432')}/{os.environ['DB_NAME']}"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')

db.init_app(app)

HARDCODED_USER_EMAIL = os.environ.get('APP_USER_EMAIL', 'admin@example.com')

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
    """Return the definite article for a noun, or None if unknown."""
    lang = language.split('-')[0].lower()
    table = _ARTICLES.get(lang, {})
    return table.get((noun_gender, bool(noun_is_plural)))


def expected_answer(card, target_language):
    """Return the full correct answer, prepending the article for nouns."""
    if card.part_of_speech == 'noun' and card.noun_gender:
        article = get_article(card.noun_gender, card.noun_is_plural, target_language)
        if article:
            return f"{article} {card.target_expression}"
    return card.target_expression


def _safe_return_url(url, fallback):
    """Validate that a return URL is a local path to prevent open redirect."""
    if url and url.startswith('/') and not url.startswith('//'):
        return url
    return fallback


def _do_quiz_check(deck, card, action, answer, check_url, next_url, return_url):
    """Shared quiz answer-checking logic for deck and study-set quiz routes."""
    if action == 'flip':
        has_expr, has_ex = audio_status(card.id)
        return render_template('quiz.html', deck=deck, card=card, state='back',
                               answer=None, correct=None,
                               full_answer=expected_answer(card, deck.target_language),
                               has_expression_audio=has_expr, has_example_audio=has_ex,
                               audio_pause_ms=int(os.environ.get('CARD_FLIP_INTER_AUDIO_PAUSE_MS', '1500')),
                               check_url=check_url, next_url=next_url, return_url=return_url)

    # For nouns: check whether the user omitted the article entirely.
    if card.part_of_speech == 'noun' and card.noun_gender:
        article = get_article(card.noun_gender, card.noun_is_plural, deck.target_language)
        if article and answer.lower().split() == card.target_expression.lower().split():
            return render_template('quiz.html', deck=deck, card=card,
                                   state='needs_article', answer=answer,
                                   expected_article=article,
                                   check_url=check_url, next_url=next_url, return_url=return_url)

    full    = expected_answer(card, deck.target_language)
    correct = answer.lower() == full.lower()
    has_expr, has_ex = audio_status(card.id)
    return render_template('quiz.html', deck=deck, card=card, state='back',
                           answer=answer, correct=correct, full_answer=full,
                           has_expression_audio=has_expr, has_example_audio=has_ex,
                           audio_pause_ms=int(os.environ.get('AUDIO_PAUSE_MS', '1500')),
                           check_url=check_url, next_url=next_url, return_url=return_url)


@app.route('/')
def index():
    return redirect(url_for('decks'))


@app.route('/decks')
def decks():
    user = User.query.filter_by(email=HARDCODED_USER_EMAIL).first_or_404()
    user_decks = Deck.query.filter_by(user_id=user.id).all()
    return render_template('decks.html', decks=user_decks, user=user)


@app.route('/deck/<int:deck_id>')
def deck_detail(deck_id):
    deck       = Deck.query.get_or_404(deck_id)
    study_sets = StudySet.query.filter_by(deck_id=deck_id).order_by(StudySet.name).all()
    card_count = Card.query.filter_by(deck_id=deck_id).count()
    return render_template('deck.html', deck=deck, study_sets=study_sets, card_count=card_count)


@app.route('/deck/<int:deck_id>/study-sets/new', methods=['GET', 'POST'])
def new_study_set(deck_id):
    from query_parser import parse, QueryParseError
    deck = Deck.query.get_or_404(deck_id)

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
        ss  = StudySet(deck_id=deck_id, name=name, tag_query=query,
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
    deck_id   = study_set.deck_id
    db.session.delete(study_set)
    db.session.commit()
    return redirect(url_for('deck_detail', deck_id=deck_id))


@app.route('/study-set/<int:set_id>/quiz')
def study_set_quiz(set_id):
    from query_parser import build_filter, QueryParseError
    study_set = StudySet.query.get_or_404(set_id)
    deck      = Deck.query.get_or_404(study_set.deck_id)
    try:
        filt = build_filter(study_set.tag_query, deck.id)
        card = (Card.query.filter_by(deck_id=deck.id)
                          .filter(filt)
                          .order_by(db.func.random())
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
    study_set = StudySet.query.get_or_404(set_id)
    deck      = Deck.query.get_or_404(study_set.deck_id)
    card      = Card.query.get_or_404(int(request.form['card_id']))
    action    = request.form.get('action')
    answer    = request.form.get('answer', '').strip()
    check_url  = url_for('study_set_check', set_id=set_id)
    next_url   = url_for('study_set_quiz',  set_id=set_id)
    return_url = url_for('study_set_quiz',  set_id=set_id)
    return _do_quiz_check(deck, card, action, answer, check_url, next_url, return_url)


@app.route('/quiz/<int:deck_id>')
def quiz(deck_id):
    deck  = Deck.query.get_or_404(deck_id)
    card  = Card.query.filter_by(deck_id=deck_id).order_by(db.func.random()).first_or_404()
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

NOUN_GENDERS = ['masculine', 'feminine']


@app.route('/card/<int:card_id>/edit', methods=['GET', 'POST'])
def edit_card(card_id):
    card = Card.query.get_or_404(card_id)
    deck = Deck.query.get_or_404(card.deck_id)
    fallback_url = url_for('quiz', deck_id=deck.id)

    if request.method == 'POST':
        new_target_expression = request.form['target_expression'].strip()
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

        card.source_expression = request.form['source_expression'].strip()
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
    return render_template('edit_card.html', card=card, deck=deck,
                           parts_of_speech=PARTS_OF_SPEECH, noun_genders=NOUN_GENDERS,
                           has_expression_audio=card.expression_audio is not None,
                           has_example_audio=card.example_audio is not None,
                           return_url=return_url)


@app.route('/deck/<int:deck_id>/cards/new', methods=['GET', 'POST'])
def add_card(deck_id):
    deck = Deck.query.get_or_404(deck_id)
    fallback_url = url_for('deck_detail', deck_id=deck_id)

    if request.method == 'POST':
        expression_audio_b64 = request.form.get('expression_audio_b64', '').strip()
        example_audio_b64    = request.form.get('example_audio_b64', '').strip()
        card = Card(
            deck_id=deck_id,
            source_expression=request.form['source_expression'].strip(),
            source_example=request.form.get('source_example', '').strip() or None,
            target_expression=request.form['target_expression'].strip(),
            target_example=request.form.get('target_example', '').strip() or None,
            part_of_speech=request.form.get('part_of_speech') or None,
            noun_gender=request.form.get('noun_gender') or None,
            noun_is_plural='noun_is_plural' in request.form,
            notes=request.form.get('notes', '').strip() or None,
            expression_audio=base64.b64decode(expression_audio_b64) if expression_audio_b64 else None,
            example_audio=base64.b64decode(example_audio_b64) if example_audio_b64 else None,
        )
        db.session.add(card)
        db.session.flush()
        for tag_name in request.form.getlist('tag'):
            tag_name = tag_name.strip()
            if not tag_name:
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
    return render_template('edit_card.html', card=stub, deck=deck,
                           parts_of_speech=PARTS_OF_SPEECH, noun_genders=NOUN_GENDERS,
                           has_expression_audio=False, has_example_audio=False,
                           return_url=return_url,
                           form_action=url_for('add_card', deck_id=deck_id))


@app.route('/card/<int:card_id>/quiz')
def quiz_card(card_id):
    card  = Card.query.get_or_404(card_id)
    deck  = Deck.query.get_or_404(card.deck_id)
    check_url  = url_for('quiz_check', deck_id=deck.id)
    next_url   = url_for('quiz',       deck_id=deck.id)
    return_url = url_for('quiz',       deck_id=deck.id)
    return render_template('quiz.html', deck=deck, card=card, state='front',
                           check_url=check_url, next_url=next_url, return_url=return_url)


@app.route('/quiz/<int:deck_id>/check', methods=['POST'])
def quiz_check(deck_id):
    deck      = Deck.query.get_or_404(deck_id)
    card      = Card.query.get_or_404(int(request.form['card_id']))
    action    = request.form.get('action')
    answer    = request.form.get('answer', '').strip()
    check_url  = url_for('quiz_check', deck_id=deck_id)
    next_url   = url_for('quiz',       deck_id=deck_id)
    return_url = url_for('quiz',       deck_id=deck_id)
    return _do_quiz_check(deck, card, action, answer, check_url, next_url, return_url)


@app.route('/deck/<int:deck_id>/tags')
def deck_tags(deck_id):
    """Return JSON list of tag names in this deck, optionally filtered by prefix."""
    Deck.query.get_or_404(deck_id)  # verify deck exists
    q    = request.args.get('q', '').strip().lower()
    tags = Tag.query.filter_by(deck_id=deck_id)
    if q:
        tags = tags.filter(db.func.lower(Tag.name).startswith(q))
    tags = tags.order_by(Tag.name).all()
    return jsonify(tags=[t.name for t in tags])


@app.route('/card/<int:card_id>/tags/add', methods=['POST'])
def card_tag_add(card_id):
    card = Card.query.get_or_404(card_id)
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify(error='Tag name required'), 400
    if ' ' in name:
        return jsonify(error='Tag names may not contain spaces'), 400

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
    card  = Card.query.get_or_404(card_id)
    audio = card.expression_audio if field == 'expression' else card.example_audio
    if not audio:
        abort(404)
    return Response(audio, mimetype='audio/mpeg',
                    headers={'Cache-Control': 'no-store'})


def _with_article(text, part_of_speech, noun_gender, noun_is_plural, language):
    if part_of_speech == 'noun' and noun_gender:
        article = get_article(noun_gender, noun_is_plural, language)
        if article:
            return f"{article} {text}"
    return text


@app.route('/card/<int:card_id>/audio/<field>/generate', methods=['POST'])
def generate_audio(card_id, field):
    if field not in ('expression', 'example'):
        abort(404)
    try:
        from tts import generate_audio as tts_generate
        card = Card.query.get_or_404(card_id)
        deck = Deck.query.get_or_404(card.deck_id)

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
