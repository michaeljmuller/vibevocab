from math import ceil


def sm2(ease_factor, interval_days, repetitions, quality):
    """SM-2 spaced repetition algorithm.

    Returns (new_ease_factor, new_interval_days, new_repetitions).
    quality: 0–5 per SM-2 spec (0=blackout, 5=perfect).
    """
    if quality >= 3:
        if repetitions == 0:
            new_interval = 1
        elif repetitions == 1:
            new_interval = 6
        else:
            new_interval = ceil(interval_days * ease_factor)
        new_repetitions = repetitions + 1
    else:
        new_interval = 1
        new_repetitions = 0

    new_ef = max(1.3, ease_factor + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    return new_ef, new_interval, new_repetitions


def quality_from_result(correct, was_flipped, response_time_ms):
    """Map a quiz result to an SM-2 quality score (0–5)."""
    if was_flipped or not correct:
        return 1
    if response_time_ms < 5000:
        return 5
    if response_time_ms < 15000:
        return 4
    return 3


def familiarity_label(repetitions):
    """Human-readable familiarity level based on consecutive correct recalls."""
    if repetitions == 0:  return 'Unlearned'
    if repetitions < 3:   return 'Learning'
    if repetitions < 6:   return 'Familiar'
    return 'Known'
