import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import AuthSettings, decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    settings = AuthSettings()
    try:
        user_id = int(decode_access_token(token, settings))
    except (jwt.PyJWTError, ValueError):
        raise unauthorized from None

    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise unauthorized
    return user
