"""Expected business failures, distinct from programmer and infrastructure errors."""


class Conflict(ValueError):
    code = 'conflict'


class JourneyNotFound(KeyError):
    code = 'journey_not_found'
