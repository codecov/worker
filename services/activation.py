from sqlalchemy import func


def activate_user(db_session, org_ownerid: int, user_ownerid: int) -> bool:
    """
    Attempt to activate the user for the given org

    Returns:
        bool: was the user successfully activated
    """
    # TODO: we need to decide the best way for this logic to be shared across
    # worker and codecov-api - ideally moving logic from database to application layer
    (activation_success,) = db_session.query(
        func.public.try_to_auto_activate(org_ownerid, user_ownerid)
    ).first()

    log.info(
        f"Auto activation was {'' if activation_success else 'not'} successful",
        extra=dict(org_ownerid=org_ownerid, author_ownerid=user_ownerid,),
    )
    return activation_success
