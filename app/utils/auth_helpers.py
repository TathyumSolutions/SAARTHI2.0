"""
Shared helper for resolving the JWT-authenticated user, used by any route
that needs to tag a resource with company_code/created_by_user_id.
"""
from flask_jwt_extended import get_jwt_identity
from app.models.user import User


def get_current_user():
    """Returns the User for the current JWT identity, or None."""
    identity = get_jwt_identity()
    if not identity:
        return None
    return User.query.get(int(identity))
