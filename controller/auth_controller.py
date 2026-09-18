from utils.date_helper import now_ist
import hashlib
from datetime import datetime, timedelta

import jwt
from flask import request, g
from sqlalchemy import text, func

from .email_controller import send_email, send_registration_email, send_login_email, send_password_changed_email

from database.dbConnection import get_session
from middleware.authMiddleware import token_required
from model.models import User, Role, Parent, Student
from utils.config import config
from utils.errors import AppError, UnauthorizedError
from utils.response import success
from utils.audit_helper import log_audit
from utils.security import (
    hash_password, verify_password, create_access_token, create_refresh_token,
    decode_token,
)
from utils.validators import require_fields, validate_email, validate_password_strength, validate_username

# pyrefly: ignore [missing-import]
from google.oauth2 import id_token as google_id_token
# pyrefly: ignore [missing-import]
from google.auth.transport import requests as google_requests



def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _issue_tokens(session, user_id: int, role_name: str) -> dict:
    normalized_role = str(role_name).strip().upper()
    access_token = create_access_token(user_id, normalized_role)
    refresh_token = create_refresh_token(user_id, normalized_role)
    expires_at = now_ist() + timedelta(days=config.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

    try:
        session.execute(
            text("CALL sp_save_refresh_token(:user_id, :token_hash, :expires_at)"),
            {
                "user_id": user_id,
                "token_hash": _hash_token(refresh_token),
                "expires_at": expires_at,
            }
        )
    except Exception:
        from model.models import RefreshToken
        try:
            token_rec = RefreshToken(
                user_id=user_id,
                token_hash=_hash_token(refresh_token),
                expires_at=expires_at,
            )
            session.add(token_rec)
            session.flush()
        except Exception:
            pass
    return {"accessToken": access_token, "refreshToken": refresh_token}


def get_page_access_for_role(session, role_name: str) -> list[dict]:
    try:
        rows = session.execute(
            text("CALL sp_get_role_menu_permissions(:role_name)"),
            {"role_name": role_name}
        ).mappings().all()

        return [
            {
                "id": r["id"],
                "pageName": r["page_name"],
                "pageRoute": r["page_route"],
                "icon": r["icon"],
                "menuOrder": r["menu_order"],
                "isActive": r["is_active"],
            }
            for r in rows
        ]
    except Exception:
        from model.models import Role, RolePageAccess
        role = session.query(Role).filter(func.lower(Role.role_name) == func.lower(role_name)).first()
        if not role:
            return []
        items = session.query(RolePageAccess).filter(
            RolePageAccess.role_id == role.id,
            RolePageAccess.is_active == True
        ).order_by(RolePageAccess.menu_order).all()
        return [
            {
                "id": item.id,
                "pageName": item.page_name,
                "pageRoute": item.page_route,
                "icon": item.icon,
                "menuOrder": item.menu_order,
                "isActive": item.is_active,
            }
            for item in items
        ]


_get_page_access = get_page_access_for_role


def register():
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["name", "username", "email", "password"])
    validate_username(payload["username"])
    validate_email(payload["email"])
    validate_password_strength(payload["password"])

    name = payload["name"].strip()
    username = payload["username"].strip()
    email = payload["email"].strip().lower()
    password_hash = hash_password(payload["password"])
    requested_role = str(payload.get("role", "PARENT")).strip().upper()
    role_name = "TEACHER" if requested_role == "TEACHER" else "PARENT"

    with get_session() as session:
        # Check global username uniqueness
        existing_username = session.query(User).filter(func.lower(User.username) == func.lower(username)).first()
        if existing_username:
            raise AppError("USERNAME_TAKEN", "This username is already taken. Please choose another username.", 409)

        # Check email uniqueness for parent / teacher
        existing_email = session.query(User).filter(func.lower(User.email) == func.lower(email)).first()
        if existing_email:
            raise AppError("EMAIL_TAKEN", "An account with this email already exists.", 409)

        role = session.query(Role).filter(Role.role_name == role_name).first()
        if not role:
            role = Role(role_name=role_name, is_active=True)
            session.add(role)
            session.flush()

        user = User(
            name=name,
            username=username,
            email=email,
            password_hash=password_hash,
            role_id=role.id,
            is_active=True,
        )
        session.add(user)
        session.flush()

        if role_name == "PARENT":
            parent = Parent(id=user.id)
            session.add(parent)
            session.flush()

        tokens = _issue_tokens(session, user.id, role_name)
        page_access = _get_page_access(session, role_name)
        session.commit()

        # Send registration welcome email
        send_registration_email(to_email=user.email, name=user.name, username=user.username, role_name=role_name)

        return success(
            {
                "tokens": {
                    "accessToken": tokens["accessToken"],
                    "refreshToken": tokens["refreshToken"],
                    "tokenType": "Bearer",
                    "expiresIn": config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                },
                "accessToken": tokens["accessToken"],
                "refreshToken": tokens["refreshToken"],
                "user": {
                    "id": user.id,
                    "name": user.name,
                    "username": user.username,
                    "email": user.email,
                    "roleId": user.role_id,
                    "roleName": role_name,
                    "role": role_name.lower(),
                    "isActive": user.is_active,
                    "createdAt": user.created_at.isoformat() if user.created_at else None,
                },
                "pageAccess": page_access,
            },
            status_code=201,
            message="User registered successfully",
        )


def login():
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["username", "password"])

    username = payload["username"].strip()
    password = payload["password"]

    with get_session() as session:
        user = session.query(User).filter(func.lower(User.username) == func.lower(username)).first()

        if not user:
            # Optional fallback check on email if someone entered their email
            user = session.query(User).filter(func.lower(User.email) == func.lower(username)).first()

        if not user:
            raise UnauthorizedError("Invalid username or password", code="INVALID_CREDENTIALS")
        
        if not user.password_hash:
            raise UnauthorizedError(
                "This account was registered with Google. Please use your credentials.",
                code="GOOGLE_AUTH_REQUIRED"
            )

        if not verify_password(password, user.password_hash):
            log_audit(
                session,
                action="LOGIN_FAILED",
                user_id=user.id if user else None,
                entity_type="USER",
                entity_id=username,
                request=request,
            )
            session.commit()
            raise UnauthorizedError("Invalid username or password", code="INVALID_CREDENTIALS")
        if not user.is_active:
            raise UnauthorizedError("This account is not active", code="ACCOUNT_INACTIVE")

        role_name = user.role.role_name if user.role else "STUDENT"
        tokens = _issue_tokens(session, user.id, role_name)
        page_access = _get_page_access(session, role_name)

        log_audit(
            session,
            action="LOGIN_SUCCESS",
            user_id=user.id,
            entity_type="USER",
            entity_id=user.name,
            request=request,
        )
        session.commit()

        # Send login notification email
        send_login_email(to_email=user.email, name=user.name, login_type="Standard")

        return success(
            {
                "tokens": {
                    "accessToken": tokens["accessToken"],
                    "refreshToken": tokens["refreshToken"],
                    "tokenType": "Bearer",
                    "expiresIn": config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                },
                "accessToken": tokens["accessToken"],
                "refreshToken": tokens["refreshToken"],
                "user": {
                    "id": user.id,
                    "name": user.name,
                    "username": user.username,
                    "email": user.email,
                    "roleId": user.role_id,
                    "roleName": role_name,
                    "role": role_name.lower(),
                    "authProvider": user.auth_provider if hasattr(user, "auth_provider") else "LOCAL",
                    "isActive": user.is_active,
                },
                "pageAccess": page_access,
            },
            status_code=200,
            message="Login successful",
        )


def admin_login():
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["email", "password"])

    email = payload["email"].strip()

    with get_session() as session:
        user = session.query(User).filter(
            (func.lower(User.email) == func.lower(email)) |
            (func.lower(User.name) == func.lower(email)) |
            (func.lower(User.username) == func.lower(email))
        ).first()

        if not user or not user.password_hash or not verify_password(payload["password"], user.password_hash):
            log_audit(
                session,
                action="ADMIN_LOGIN_FAILED",
                entity_type="USER",
                entity_id=email,
                request=request,
            )
            session.commit()
            raise UnauthorizedError("Invalid email or password", code="INVALID_CREDENTIALS")

        if not user.is_active:
            raise UnauthorizedError("This account is not active", code="ACCOUNT_INACTIVE")

        role_name = (user.role.role_name if user.role else "ADMIN").strip().upper()
        if role_name not in ["ADMIN", "SUPER_ADMIN"]:
            raise UnauthorizedError("Access restricted to administrators", code="FORBIDDEN_ROLE")

        tokens = _issue_tokens(session, user.id, role_name)
        try:
            page_access = _get_page_access(session, role_name)
        except Exception:
            page_access = []

        log_audit(
            session,
            action="ADMIN_LOGIN_SUCCESS",
            user_id=user.id,
            entity_type="USER",
            entity_id=user.name,
            request=request,
        )
        session.commit()

        return success(
            {
                "tokens": {
                    "accessToken": tokens["accessToken"],
                    "refreshToken": tokens["refreshToken"],
                    "tokenType": "Bearer",
                    "expiresIn": config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                },
                "accessToken": tokens["accessToken"],
                "refreshToken": tokens["refreshToken"],
                "user": {
                    "id": user.id,
                    "name": user.name,
                    "username": user.username,
                    "email": user.email,
                    "roleId": user.role_id,
                    "roleName": role_name,
                    "role": role_name.lower(),
                    "isActive": user.is_active,
                },
                "pageAccess": page_access,
            },
            status_code=200,
            message="Admin login successful",
        )


def reset_password():
    """Public password reset for Parents, Students, and Teachers."""
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["identifier", "newPassword"])

    identifier = str(payload["identifier"]).strip()
    new_password = str(payload["newPassword"])

    if len(new_password) < 6:
        raise AppError("WEAK_PASSWORD", "Password must be at least 6 characters.", 400)

    with get_session() as session:
        # Search primarily by username (case-insensitive)
        user = session.query(User).filter(
            func.lower(User.username) == identifier.lower()
        ).first()

        # Fallback to email only if no account was matched by username
        if not user:
            user = session.query(User).filter(
                func.lower(User.email) == identifier.lower()
            ).first()

        if not user:
            raise AppError("NOT_FOUND", f"No account found with username '{identifier}'.", 404)

        # Get role name
        role = session.query(Role).filter(Role.id == user.role_id).first()
        role_name = role.role_name if role else "User"

        # Determine target email for security confirmation notification
        target_email = user.email

        # If student account without direct email, find linked parent email
        if not target_email and user.role_id == 1:
            student = session.query(Student).filter(Student.id == user.id).first()
            if student and student.parent_id:
                parent_user = session.query(User).filter(User.id == student.parent_id).first()
                if parent_user and parent_user.email:
                    target_email = parent_user.email

        user.password_hash = hash_password(new_password)
        user.updated_at = now_ist()
        session.commit()

        # Dispatch confirmation email if target email is available
        if target_email:
            send_password_changed_email(
                to_email=target_email,
                name=user.name,
                username=user.username,
                role_name=role_name,
            )

        log_audit(
            session,
            action="PASSWORD_RESET",
            user_id=user.id,
            entity_type="USER",
            entity_id=str(user.id),
        )

        return success({"reset": True}, message="Password updated successfully. A confirmation email has been sent.")


def admin_reset_password():
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["email", "newPassword"])

    email = payload["email"].strip()
    new_password = payload["newPassword"]

    if len(new_password) < 6:
        raise AppError("WEAK_PASSWORD", "Password must be at least 6 characters.", 400)

    with get_session() as session:
        user = session.query(User).filter((User.email == email) | (User.name == email) | (User.username == email)).first()
        if not user:
            raise AppError("NOT_FOUND", "Admin account not found", 404)

        if user.role_id != 4:
            raise UnauthorizedError("Password reset only available for admin accounts here", code="FORBIDDEN_ROLE")

        user.password_hash = hash_password(new_password)
        user.updated_at = now_ist()
        session.commit()

        if user.email:
            send_password_changed_email(
                to_email=user.email,
                name=user.name,
                username=user.username,
                role_name="Admin",
            )

        log_audit(
            session,
            action="ADMIN_PASSWORD_RESET",
            user_id=user.id,
            entity_type="USER",
            entity_id=str(user.id),
        )

        return success({"reset": True}, message="Password updated successfully. A confirmation email has been sent.")


def google_auth():
    """Authenticates or registers a user via Google OAuth ID Token or Access Token."""
    payload = request.get_json(force=True, silent=True) or {}
    token = payload.get("credential") or payload.get("token") or payload.get("idToken") or payload.get("accessToken")
    if not token:
        raise AppError("MISSING_TOKEN", "Google credential token is required", 400)

    email = None
    name = None
    google_id = None

    token_str = str(token).strip()

    if token_str.count('.') == 2:
        # JWT ID Token flow
        try:
            audience = config.GOOGLE_CLIENT_ID if config.GOOGLE_CLIENT_ID else None
            id_info = google_id_token.verify_oauth2_token(
                token_str,
                google_requests.Request(),
                audience=audience,
                clock_skew_in_seconds=10
            )
            email = id_info.get("email")
            google_id = id_info.get("sub")
            name = id_info.get("name")
        except Exception as e:
            raise UnauthorizedError(f"Invalid Google ID token: {str(e)}", code="INVALID_GOOGLE_TOKEN")
    else:
        # OAuth2 Access Token flow
        import requests
        try:
            res = requests.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {token_str}"},
                timeout=10
            )
            if res.status_code != 200:
                raise UnauthorizedError("Failed to verify Google access token", code="INVALID_GOOGLE_TOKEN")
            user_data = res.json()
            email = user_data.get("email")
            google_id = user_data.get("sub")
            name = user_data.get("name")
        except Exception as e:
            raise UnauthorizedError(f"Google authentication error: {str(e)}", code="INVALID_GOOGLE_TOKEN")

    if not email:
        raise AppError("INVALID_TOKEN", "Google account did not provide a verified email", 400)

    import uuid
    name = name or email.split("@")[0]
    email = email.strip().lower()
    requested_role = str(payload.get("role", "PARENT")).strip().upper()
    role_name = "TEACHER" if requested_role == "TEACHER" else "PARENT"
    provided_username = (payload.get("username") or "").strip()

    with get_session() as session:
        # Check if user already exists with this email
        user = session.query(User).filter(func.lower(User.email) == email).first()

        if not user:
            # If new user and no username provided, request username from frontend
            if not provided_username:
                return success({
                    "requiresUsername": True,
                    "email": email,
                    "name": name,
                    "googleId": google_id,
                    "token": token_str,
                }, message="Please provide a username to complete registration")
            
            # Username provided - validate and register
            validate_username(provided_username)
            existing_user = session.query(User).filter(func.lower(User.username) == func.lower(provided_username)).first()
            if existing_user:
                raise AppError("USERNAME_TAKEN", f"The username '{provided_username}' is already taken. Please choose another username.", 409)

            role = session.query(Role).filter(Role.role_name == role_name).first()
            if not role:
                role = Role(role_name=role_name, is_active=True)
                session.add(role)
                session.flush()

            user = User(
                name=name.strip(),
                username=provided_username,
                email=email,
                password_hash=hash_password(uuid.uuid4().hex[:12]),
                role_id=role.id,
                is_active=True,
            )
            session.add(user)
            session.flush()

            if role_name == "PARENT":
                parent = Parent(id=user.id)
                session.add(parent)
                session.flush()

        if not user.is_active:
            raise UnauthorizedError("This account is not active", code="ACCOUNT_INACTIVE")

        user_role_name = user.role.role_name if user.role else role_name
        tokens = _issue_tokens(session, user.id, user_role_name)
        page_access = _get_page_access(session, user_role_name)

        log_audit(
            session,
            action="GOOGLE_LOGIN_SUCCESS",
            user_id=user.id,
            entity_type="USER",
            entity_id=str(user.id),
            request=request,
        )
        session.commit()

        # Send Google login notification email
        send_login_email(to_email=user.email, name=user.name, login_type="Google")

        created_at_str = user.created_at.isoformat() if user.created_at else None

        return success(
            {
                "tokens": {
                    "accessToken": tokens["accessToken"],
                    "refreshToken": tokens["refreshToken"],
                    "tokenType": "Bearer",
                    "expiresIn": config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                },
                "accessToken": tokens["accessToken"],
                "refreshToken": tokens["refreshToken"],
                "user": {
                    "id": user.id,
                    "name": user.name,
                    "username": user.username,
                    "email": user.email,
                    "roleId": user.role_id,
                    "roleName": user_role_name,
                    "role": user_role_name.lower(),
                    "isActive": user.is_active,
                    "createdAt": created_at_str,
                },
                "pageAccess": page_access,
            },
            status_code=200,
            message="Google login successful",
        )


def check_username():
    """Checks whether a proposed username is available and valid globally."""
    username = (request.args.get("username") or "").strip()
    if not username:
        return success({"available": False, "reason": "Username is required"})
    try:
        validate_username(username)
    except Exception as e:
        msg = e.message if hasattr(e, "message") else str(e)
        return success({"available": False, "reason": msg})
    
    with get_session() as session:
        existing = session.query(User).filter(func.lower(User.username) == func.lower(username)).first()
        if existing:
            return success({"available": False, "reason": "Username is already taken"})
        return success({"available": True, "username": username})


@token_required
def verify_session():
    """Validates the current session token with the database."""
    user_id = g.current_user_id

    with get_session() as session:
        user = session.get(User, user_id)

        if not user or not user.is_active:
            raise UnauthorizedError("Session invalid or account inactive", code="SESSION_INVALID")

        role_name = user.role.role_name if user.role else "STUDENT"
        page_access = _get_page_access(session, role_name)

        return success(
            {
                "valid": True,
                "user": {
                    "id": user.id,
                    "name": user.name,
                    "username": user.username,
                    "email": user.email,
                    "roleId": user.role_id,
                    "roleName": role_name,
                    "role": role_name.lower(),
                    "isActive": user.is_active,
                },
                "pageAccess": page_access,
            },
            status_code=200,
            message="Session verified successfully",
        )


@token_required
def get_menu_permissions():
    """Returns dynamic page access & navigation permissions for the active role."""
    role_name = g.current_user_role

    with get_session() as session:
        page_access = _get_page_access(session, role_name)
        return success(
            {"role": role_name, "menuItems": page_access, "pageAccess": page_access},
            status_code=200,
            message="Menu permissions retrieved successfully",
        )


def get_registration_roles():
    """Public endpoint to fetch active roles available for self-registration."""
    with get_session() as session:
        rows = session.execute(text("CALL sp_get_registration_roles()")).mappings().all()
        roles_list = [
            {
                "id": r["id"],
                "roleName": r["role_name"],
                "displayName": r["display_name"],
                "description": r["description"],
                "icon": r["icon"],
                "isActive": r["is_active"],
            }
            for r in rows
        ]
        return success(
            roles_list,
            status_code=200,
            message="Registration roles retrieved successfully",
        )



@token_required
def child_login():
    """Deprecated: Students must log in with their username and password on /login."""
    raise AppError("DEPRECATED", "Child PIN login is deprecated. Students must log in with their Username and Password.", 400)


def refresh():
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["refreshToken"])
    raw_token = payload["refreshToken"]

    try:
        decoded = decode_token(raw_token)
    except jwt.PyJWTError:
        raise UnauthorizedError("Invalid or expired refresh token", code="TOKEN_INVALID")
    if decoded.get("type") != "refresh":
        raise UnauthorizedError("Not a refresh token")

    token_hash = _hash_token(raw_token)

    with get_session() as session:
        try:
            user = session.execute(
                text("CALL sp_validate_and_rotate_refresh_token(:token_hash)"),
                {"token_hash": token_hash}
            ).mappings().first()
            session.commit()
        except Exception:
            raise UnauthorizedError("Refresh token expired or revoked", code="TOKEN_EXPIRED")

        if not user or not user["is_active"]:
            raise UnauthorizedError("User no longer exists or is inactive")

        tokens = _issue_tokens(session, user["id"], user["role_name"])
        page_access = _get_page_access(session, user["role_name"])
        session.commit()

        return success(
            {
                "tokens": {
                    "accessToken": tokens["accessToken"],
                    "refreshToken": tokens["refreshToken"],
                    "tokenType": "Bearer",
                    "expiresIn": config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                },
                "accessToken": tokens["accessToken"],
                "refreshToken": tokens["refreshToken"],
                "pageAccess": page_access,
            },
            status_code=200,
            message="Token refreshed successfully",
        )


@token_required
def logout():
    payload = request.get_json(force=True, silent=True) or {}
    raw_refresh = payload.get("refreshToken")
    if raw_refresh:
        with get_session() as session:
            session.execute(
                text("CALL sp_revoke_refresh_token(:token_hash)"),
                {"token_hash": _hash_token(raw_refresh)}
            )
            session.commit()
    return success({"loggedOut": True}, status_code=200, message="Logged out successfully")
