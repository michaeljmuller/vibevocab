import os
from flask import Flask, render_template, redirect, url_for, request, abort
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
        card.source_expression = request.form['source_expression'].strip()
        card.source_example    = request.form.get('source_example', '').strip() or None
        card.target_expression = request.form['target_expression'].strip()
        card.target_example    = request.form.get('target_example', '').strip() or None
        card.part_of_speech    = request.form.get('part_of_speech') or None
        card.noun_gender       = request.form.get('noun_gender') or None
        card.noun_is_plural    = 'noun_is_plural' in request.form
        card.notes             = request.form.get('notes', '').strip() or None
        db.session.commit()
        return redirect(url_for('quiz', deck_id=deck.id))

    return render_template('edit_card.html', card=card, deck=deck,
                           parts_of_speech=PARTS_OF_SPEECH, noun_genders=NOUN_GENDERS)


@app.route('/quiz/<int:deck_id>/check', methods=['POST'])
def quiz_check(deck_id):
    deck   = Deck.query.get_or_404(deck_id)
    card   = Card.query.get_or_404(int(request.form['card_id']))
    action = request.form.get('action')
    answer = request.form.get('answer', '').strip()

    if action == 'flip':
        return render_template('quiz.html', deck=deck, card=card, state='back',
                               answer=None, correct=None,
                               full_answer=expected_answer(card, deck.target_language))

    # For nouns: check whether the user omitted the article entirely.
    if card.part_of_speech == 'noun' and card.noun_gender:
        article = get_article(card.noun_gender, card.noun_is_plural, deck.target_language)
        if article and answer.lower().split() == card.target_expression.lower().split():
            return render_template('quiz.html', deck=deck, card=card,
                                   state='needs_article', answer=answer,
                                   expected_article=article)

    full = expected_answer(card, deck.target_language)
    correct = answer.lower() == full.lower()
    return render_template('quiz.html', deck=deck, card=card, state='back',
                           answer=answer, correct=correct, full_answer=full)
