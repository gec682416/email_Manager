from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.models import User


def get_or_create_local_user(db: Session) -> User:
    user = db.query(User).filter(User.email == "local@example.com").first()
    if user:
        return user
    user = User(email="local@example.com", display_name="Local User", timezone=settings.default_timezone)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
