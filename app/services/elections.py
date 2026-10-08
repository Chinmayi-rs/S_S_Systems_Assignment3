from app.models.election import Election


def current_election():
    open_election = (
        Election.query.filter_by(status='open').order_by(Election.id.desc()).first()
    )
    if open_election:
        return open_election
    return Election.query.order_by(Election.id.desc()).first()
