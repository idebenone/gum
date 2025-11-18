import os
from datetime import datetime, timedelta
from datetime import date as date_type

import jwt
from fastapi import HTTPException
from sqlalchemy import select

from ..schemas.auth_schemas import LoginPayload, RegisterPayload
from gum import gum as GumClass
from gum.models import User


async def login_user_service(payload: LoginPayload, g: GumClass):
    """Authenticate user and return a JWT access token.

    Note: passwords are stored in plaintext in this implementation. For
    production use a secure password hash (bcrypt) and secure secret.
    """

    async with g._session() as session:
        res = await session.execute(select(User).where(User.username == payload.username))
        user = res.scalars().first()
        if user is None or user.password != payload.password:
            raise HTTPException(status_code=401, detail="invalid credentials")
    
    secret = os.getenv("JWT_SECRET", "change-me")
    now = datetime.utcnow()
    exp = now + timedelta(hours=24)
    token = jwt.encode({"sub": user.username, "user_id": user.id, "exp": exp}, secret, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expires_at": exp.isoformat()}


async def register_user_service(payload: RegisterPayload, g: GumClass):
    """Register or update a user in the database.

    This will create a gum instance for the user (if needed) and persist
    the provided profile fields. Password is stored verbatim here; in
    production you should hash it.
    """

    if not payload.username or not payload.username.strip():
        raise HTTPException(status_code=400, detail="username is required")
    
    async with g._session() as session:
        res = await session.execute(
            select(User).where(User.username == payload.username)
        )
        user = res.scalars().first()
        if user is None:
            user = User(username=payload.username)
            session.add(user)
            await session.flush()

        # set provided fields
        if payload.first_name is not None:
            user.first_name = payload.first_name
        if payload.last_name is not None:
            user.last_name = payload.last_name
        if payload.location is not None:
            user.location = payload.location
        if payload.gender is not None:
            user.gender = payload.gender
        if payload.dob is not None:
            # Parse dob string to date object (accept DD/MM/YYYY format)
            try:
                dob_date = datetime.strptime(payload.dob, "%d/%m/%Y").date()
                user.dob = dob_date
            except ValueError:
                raise HTTPException(status_code=400, detail="dob must be in DD/MM/YYYY format")
        if payload.email is not None:
            user.email = payload.email
        if payload.password is not None:
            user.password = payload.password

        await session.commit()
    return {
        "status": "ok",
        "user": {
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "location": user.location,
            "gender": user.gender,
            "dob": str(user.dob) if getattr(user, "dob", None) is not None else None,
            "email": user.email,
        },
    }            