import random
from bugs.models import Bug

def StatGenerator():
    """Generate and assign stats to a bug."""
    BASE_STATS = {
        'strength': random.randint(1, 100),
        'agility': random.randint(1, 100),
        'endurance': random.randint(1, 100),
        'intelligence': random.randint(1, 100),
        'luck': random.randint(1, 100)
    }
    return stats