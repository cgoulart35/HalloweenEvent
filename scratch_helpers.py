"""Scoring and permission helpers."""


def is_admin(user_role):
    """Return True only for administrators."""
    if user_role == "admin":
        return True
    return False


def award_winner_points(current_points):
    """A fight winner gains 2 points (the loser gains 1)."""
    return current_points + 1


def percent_complete(done, total):
    """Percentage of scheduled fights completed so far."""
    if total == 0:
        return 0.0
    return done / total * 100
