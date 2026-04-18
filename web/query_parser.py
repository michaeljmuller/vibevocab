"""
Tag query parser and evaluator for study set filters.

Grammar:
    expr     := or_expr
    or_expr  := and_expr ('OR' and_expr)*
    and_expr := not_expr ('AND' not_expr)*
    not_expr := 'NOT' not_expr | atom
    atom     := '(' expr ')' | WORD

Keywords AND, OR, NOT are case-insensitive.  Tag names may not contain spaces.

System predicates (prefixed with _):
    _has_tags              card has at least one user tag
    _has_expression_audio  card has expression audio
    _has_example_audio     card has example audio
    _has_example           card has a target example sentence
    _has_notes             card has notes
"""
import re
from sqlalchemy import and_, or_, not_, select
from models import db, Card, Tag, card_tags


KEYWORDS = frozenset({'AND', 'OR', 'NOT'})


class QueryParseError(ValueError):
    pass


# ── Tokenizer ──────────────────────────────────────────────────────────────

def _tokenize(query):
    return re.findall(r'[()]|\S+', query)


# ── AST nodes ──────────────────────────────────────────────────────────────

class _And:
    def __init__(self, left, right): self.left, self.right = left, right

class _Or:
    def __init__(self, left, right): self.left, self.right = left, right

class _Not:
    def __init__(self, child): self.child = child

class _Tag:
    def __init__(self, name): self.name = name


# ── Parser ─────────────────────────────────────────────────────────────────

class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos    = 0

    def _peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _consume(self, expected=None):
        tok = self._peek()
        if tok is None:
            raise QueryParseError('Unexpected end of query')
        if expected is not None and tok != expected:
            raise QueryParseError(f'Expected {expected!r}, got {tok!r}')
        self.pos += 1
        return tok

    def parse(self):
        node = self._or()
        if self._peek() is not None:
            raise QueryParseError(f'Unexpected token {self._peek()!r}')
        return node

    def _or(self):
        node = self._and()
        while self._peek() and self._peek().upper() == 'OR':
            self._consume()
            node = _Or(node, self._and())
        return node

    def _and(self):
        node = self._not()
        while self._peek() and self._peek().upper() == 'AND':
            self._consume()
            node = _And(node, self._not())
        return node

    def _not(self):
        if self._peek() and self._peek().upper() == 'NOT':
            self._consume()
            return _Not(self._not())
        return self._atom()

    def _atom(self):
        tok = self._peek()
        if tok is None:
            raise QueryParseError('Unexpected end of query')
        if tok == '(':
            self._consume('(')
            node = self._or()
            self._consume(')')
            return node
        if tok == ')':
            raise QueryParseError("Unexpected ')'")
        if tok.upper() in KEYWORDS:
            raise QueryParseError(f'Unexpected keyword {tok!r}')
        self._consume()
        return _Tag(tok)


def parse(query):
    """Parse a tag query string into an AST.  Raises QueryParseError on invalid input."""
    tokens = _tokenize(query.strip())
    if not tokens:
        raise QueryParseError('Empty query')
    return _Parser(tokens).parse()


# ── Evaluator ──────────────────────────────────────────────────────────────

def _eval(node, deck_id):
    if isinstance(node, _And):
        return and_(_eval(node.left, deck_id), _eval(node.right, deck_id))
    if isinstance(node, _Or):
        return or_(_eval(node.left, deck_id), _eval(node.right, deck_id))
    if isinstance(node, _Not):
        return not_(_eval(node.child, deck_id))
    # _Tag node
    name = node.name
    if name == '_has_tags':
        return Card.id.in_(
            select(card_tags.c.card_id)
            .join(Tag, Tag.id == card_tags.c.tag_id)
            .where(Tag.deck_id == deck_id)
        )
    if name == '_has_expression_audio':
        return Card.expression_audio.isnot(None)
    if name == '_has_example_audio':
        return Card.example_audio.isnot(None)
    if name == '_has_example':
        return Card.target_example.isnot(None)
    if name == '_has_notes':
        return Card.notes.isnot(None)
    # User tag — case-insensitive match within this deck
    return Card.id.in_(
        select(card_tags.c.card_id)
        .join(Tag, Tag.id == card_tags.c.tag_id)
        .where(Tag.deck_id == deck_id)
        .where(db.func.lower(Tag.name) == name.lower())
    )


def build_filter(query, deck_id):
    """Parse a tag query string and return a SQLAlchemy filter expression.
    Use as: Card.query.filter_by(deck_id=...).filter(build_filter(query, deck_id))
    Raises QueryParseError on invalid query syntax."""
    return _eval(parse(query), deck_id)
