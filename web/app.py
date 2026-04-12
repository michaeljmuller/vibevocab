import os
import base64
from flask import Flask, render_template, redirect, url_for, request, abort, jsonify, Response
from models import db, User, Deck, Card

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


@app.route('/')
def index():
    return redirect(url_for('decks'))


@app.route('/decks')
def decks():
    user = User.query.filter_by(email=HARDCODED_USER_EMAIL).first_or_404()
    user_decks = Deck.query.filter_by(user_id=user.id).all()
    return render_template('decks.html', decks=user_decks, user=user)


@app.route('/quiz/<int:deck_id>')
def quiz(deck_id):
    deck = Deck.query.get_or_404(deck_id)
    card = Card.query.filter_by(deck_id=deck_id).order_by(db.func.random()).first_or_404()
    return render_template('quiz.html', deck=deck, card=card, state='front')


PARTS_OF_SPEECH = [
    'adjective', 'adverb', 'conjunction', 'expression',
    'interjection', 'noun', 'other', 'preposition', 'pronoun', 'verb',
]

NOUN_GENDERS = ['masculine', 'feminine']


@app.route('/card/<int:card_id>/edit', methods=['GET', 'POST'])
def edit_card(card_id):
    card = Card.query.get_or_404(card_id)
    deck = Deck.query.get_or_404(card.deck_id)

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
        return redirect(url_for('quiz', deck_id=deck.id))

    return render_template('edit_card.html', card=card, deck=deck,
                           parts_of_speech=PARTS_OF_SPEECH, noun_genders=NOUN_GENDERS,
                           has_expression_audio=card.expression_audio is not None,
                           has_example_audio=card.example_audio is not None)


@app.route('/card/<int:card_id>/quiz')
def quiz_card(card_id):
    card = Card.query.get_or_404(card_id)
    deck = Deck.query.get_or_404(card.deck_id)
    return render_template('quiz.html', deck=deck, card=card, state='front')


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

        data             = request.get_json(force=True)
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


@app.route('/card/<int:card_id>/audio/<field>/generate', methods=['POST'])
def generate_audio(card_id, field):
    if field not in ('expression', 'example'):
        abort(404)
    try:
        from tts import generate_audio as tts_generate
        Card.query.get_or_404(card_id)  # verify card exists

        data = request.get_json(force=True)
        text = (data.get('text') or '').strip()
        if not text:
            return jsonify(error='No text to generate audio for.'), 400

        audio = tts_generate(text)
        return jsonify(audio_b64=base64.b64encode(audio).decode())
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route('/quiz/<int:deck_id>/check', methods=['POST'])
def quiz_check(deck_id):
    deck   = Deck.query.get_or_404(deck_id)
    card   = Card.query.get_or_404(int(request.form['card_id']))
    action = request.form.get('action')
    answer = request.form.get('answer', '').strip()

    if action == 'flip':
        has_expr, has_ex = audio_status(card.id)
        return render_template('quiz.html', deck=deck, card=card, state='back',
                               answer=None, correct=None,
                               full_answer=expected_answer(card, deck.target_language),
                               has_expression_audio=has_expr, has_example_audio=has_ex,
                               audio_pause_ms=int(os.environ.get('CARD_FLIP_INTER_AUDIO_PAUSE_MS', '1500')))

    # For nouns: check whether the user omitted the article entirely.
    if card.part_of_speech == 'noun' and card.noun_gender:
        article = get_article(card.noun_gender, card.noun_is_plural, deck.target_language)
        if article and answer.lower().split() == card.target_expression.lower().split():
            return render_template('quiz.html', deck=deck, card=card,
                                   state='needs_article', answer=answer,
                                   expected_article=article)

    full = expected_answer(card, deck.target_language)
    correct = answer.lower() == full.lower()
    has_expr, has_ex = audio_status(card.id)
    return render_template('quiz.html', deck=deck, card=card, state='back',
                           answer=answer, correct=correct, full_answer=full,
                           has_expression_audio=has_expr, has_example_audio=has_ex,
                           audio_pause_ms=int(os.environ.get('AUDIO_PAUSE_MS', '1500')))
