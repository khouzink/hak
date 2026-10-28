"""Evidence-backed priority evaluation shared by ranking and budget optimization."""
from backend.infrastructure.poi_matrix import walking_evidence


def priority_evidence(hotel, key):
    if key == 'breakfast':
        # Hotel-level meal labels do not prove inclusion in a particular rate.
        return None
    if key == 'culture':
        candidates=[walking_evidence(hotel['id'], category) for category in ('museum','theatre','culture')]
        known=[candidate for candidate in candidates if candidate is not None]
        return any(candidate['within_limit'] for candidate in known) if known else None
    if key in ('sea','office'):
        return None
    return hotel.get(key)
