Prompt Templates
================

Prompt files use Python's string.Template format.  Placeholders are written
as $name or ${name}.  A literal dollar sign is written as $$.

To use a custom prompt, set the relevant environment variable to the path of
your file.  The default files in this directory are used when the variable is
not set.


example-sentences.txt
---------------------
Env var: LLM_SUGGESTION_PROMPT

Generates paired example sentences (source + target language) for a
vocabulary card.

Variables:
  $source_expression  The source-language word or phrase on the card.
  $target_expression  The target-language word or phrase on the card.
  $pos_hint           Part of speech, formatted as " (verb)" — empty string
                      if not set on the card.
  $source_language    BCP 47 code for the source language (e.g. en-US).
  $target_language    BCP 47 code for the target language (e.g. pt-PT).
  $count              Number of sentence pairs to generate (set via
                      SUGGESTION_COUNT env var, default 3).
  $notes_hint         The card's notes field, formatted as "\n\nNotes: ..."
                      — empty string if the card has no notes.


translate-example.txt
---------------------
Env var: LLM_TRANSLATION_PROMPT

Translates a source-language example sentence into the target language,
using the target expression. Also checks for problems (example doesn't
use the source expression, or the target expression looks wrong).

The response has two optional fields: a translation and a problem
explanation. Either or both may be present.

Variables:
  $source_expression  The source-language word or phrase on the card.
  $target_expression  The target-language word or phrase on the card.
  $source_example     The source-language example sentence to translate.
  $pos_hint           Part of speech, formatted as " (verb)" — empty
                      string if not set on the card.
  $source_language    BCP 47 code for the source language (e.g. en-US).
  $target_language    BCP 47 code for the target language (e.g. pt-PT).
  $notes_hint         The card's notes field, formatted as "\n\nNotes: ..."
                      — empty string if the card has no notes.
