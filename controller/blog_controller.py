from utils.date_helper import now_ist
"""Blog controller handling CRUD operations for blogs, categories, and authors."""
from datetime import datetime

from flask import request, g
from sqlalchemy import or_, func

from functools import wraps

from database.dbConnection import get_session
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import roles_required
from model.models import Blog, AuthorMaster, CategoryMaster
from utils.config import config
from utils.errors import NotFoundError, ValidationError, UnauthorizedError
from utils.pagination import paginated_response
from utils.response import success
from utils.security import decode_token
from utils.serializers import blog_to_dict, category_to_dict, author_to_dict
from utils.validators import require_fields
from utils.audit_helper import log_audit


def _admin_required(fn):
    """Permits authenticated ADMIN/SUPER_ADMIN, or falls back gracefully in development mode."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            try:
                payload = decode_token(token)
                role = str(payload.get("role", "")).upper()
                if role in ("ADMIN", "SUPER_ADMIN", "AUTHOR"):
                    g.current_user_id = payload.get("sub")
                    g.current_user_role = role
                    return fn(*args, **kwargs)
            except Exception:
                pass
        if config.APP_ENV == "development":
            g.current_user_id = getattr(g, "current_user_id", 1)
            g.current_user_role = getattr(g, "current_user_role", "ADMIN")
            return fn(*args, **kwargs)
        raise UnauthorizedError("Admin authorization required")

    return wrapper


def _parse_date(val):
    if not val:
        return now_ist()
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        val_clean = val.strip()
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
            "%b %d, %Y",
            "%B %d, %Y",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%Y/%m/%d",
        ):
            try:
                return datetime.strptime(val_clean, fmt)
            except ValueError:
                pass
        try:
            return datetime.fromisoformat(val_clean.replace("Z", "+00:00"))
        except Exception:
            pass
    return now_ist()


def _resolve_author(session, payload: dict) -> AuthorMaster:
    author_id = payload.get("author_id") or payload.get("authorId")
    if author_id:
        try:
            author_id_int = int(author_id)
        except (ValueError, TypeError):
            raise ValidationError("Invalid author_id")
        author = session.get(AuthorMaster, author_id_int)
        if not author:
            raise NotFoundError(f"Author with id {author_id} not found")
        return author

    author_name = payload.get("author") or payload.get("author_name") or payload.get("authorName")
    if author_name and str(author_name).strip():
        clean_name = str(author_name).strip()
        author = session.query(AuthorMaster).filter(func.lower(AuthorMaster.name) == clean_name.lower()).first()
        if not author:
            author = AuthorMaster(name=clean_name, is_active=True)
            session.add(author)
            session.flush()
        return author

    # Fallback to Admin User
    author = session.query(AuthorMaster).filter(func.lower(AuthorMaster.name) == "admin user").first()
    if not author:
        author = AuthorMaster(name="Admin User", is_active=True)
        session.add(author)
        session.flush()
    return author


def _resolve_category(session, payload: dict) -> CategoryMaster:
    category_id = payload.get("category_id") or payload.get("categoryId")
    if category_id:
        try:
            category_id_int = int(category_id)
        except (ValueError, TypeError):
            raise ValidationError("Invalid category_id")
        cat = session.get(CategoryMaster, category_id_int)
        if not cat:
            raise NotFoundError(f"Category with id {category_id} not found")
        return cat

    cat_name = payload.get("category") or payload.get("category_name") or payload.get("categoryName")
    if cat_name and str(cat_name).strip():
        clean_name = str(cat_name).strip()
        cat = session.query(CategoryMaster).filter(func.lower(CategoryMaster.name) == clean_name.lower()).first()
        if not cat:
            cat = CategoryMaster(name=clean_name, is_active=True)
            session.add(cat)
            session.flush()
        return cat

    raise ValidationError("Missing required field: category or category_id")


def _normalize_status(status_str: str | None) -> str:
    if not status_str:
        return "Draft"
    s = str(status_str).strip().lower()
    if s == "published":
        return "Published"
    elif s == "draft":
        return "Draft"
    raise ValidationError("Invalid status. Allowed values are 'Published' or 'Draft'")


def _normalize_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


# ============================================================
# Blog CRUD Handlers
# ============================================================
def list_blogs():
    """List blogs with optional search, category, author, status, and pagination filters."""
    search = request.args.get("search") or request.args.get("q")
    status_filter = request.args.get("status") or "Published"
    category_param = request.args.get("category") or request.args.get("categoryId") or request.args.get("category_id")
    author_param = request.args.get("author") or request.args.get("authorId") or request.args.get("author_id")
    page = request.args.get("page", type=int)
    limit = request.args.get("limit", type=int)

    with get_session() as session:
        query = (
            session.query(Blog)
            .outerjoin(AuthorMaster, Blog.author_id == AuthorMaster.id)
            .outerjoin(CategoryMaster, Blog.category_id == CategoryMaster.id)
        )

        if status_filter.lower() != "all":
            query = query.filter(func.lower(Blog.status) == status_filter.strip().lower())

        if category_param:
            if str(category_param).isdigit():
                query = query.filter(Blog.category_id == int(category_param))
            else:
                query = query.filter(func.lower(CategoryMaster.name) == str(category_param).strip().lower())

        if author_param:
            if str(author_param).isdigit():
                query = query.filter(Blog.author_id == int(author_param))
            else:
                query = query.filter(func.lower(AuthorMaster.name) == str(author_param).strip().lower())

        if search:
            term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Blog.title.ilike(term),
                    AuthorMaster.name.ilike(term),
                    CategoryMaster.name.ilike(term),
                )
            )

        total = query.count()
        query = query.order_by(Blog.is_pinned.desc(), Blog.date.desc(), Blog.id.desc())

        if page is not None and limit is not None and page > 0 and limit > 0:
            offset = (page - 1) * limit
            blogs = query.offset(offset).limit(limit).all()
            items = [blog_to_dict(b) for b in blogs]
            return success(paginated_response(items, total, page, limit))

        blogs = query.all()
        items = [blog_to_dict(b) for b in blogs]
        return success(items, count=total)


def get_blog(blog_id: int):
    """Retrieve a single blog by ID."""
    with get_session() as session:
        blog = session.query(Blog).filter(Blog.id == blog_id, Blog.status == "Published").first()
        if not blog:
            raise NotFoundError("Blog not found")
        return success(blog_to_dict(blog))


@_admin_required
def create_blog():
    """Create a new blog post."""
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["title"])

    title = str(payload["title"]).strip()
    heading = str(payload.get("heading") or title).strip()
    introduction = str(payload.get("introduction") or "").strip()
    content = str(payload.get("content") or "").strip()
    status = _normalize_status(payload.get("status"))
    blog_date = _parse_date(payload.get("date"))

    with get_session() as session:
        author = _resolve_author(session, payload)
        category = _resolve_category(session, payload)

        blog = Blog(
            title=title,
            introduction=introduction,
            content=content,
            image_url=str(payload.get("image_url") or payload.get("imageUrl") or "").strip() or None,
            is_pinned=bool(payload.get("is_pinned", payload.get("isPinned", False))),
            tags=_normalize_list(payload.get("tags")),
            meta_title=str(payload.get("meta_title") or payload.get("metaTitle") or "").strip() or None,
            meta_description=str(payload.get("meta_description") or payload.get("metaDescription") or "").strip() or None,
            meta_keywords=str(payload.get("meta_keywords") or payload.get("metaKeywords") or "").strip() or None,
            canonical_url=str(payload.get("canonical_url") or payload.get("canonicalUrl") or "").strip() or None,
            author_id=author.id,
            category_id=category.id,
            status=status,
            date=blog_date,
            created_at=now_ist(),
            updated_at=now_ist(),
        )
        session.add(blog)
        session.flush()

        log_audit(
            session,
            action="BLOG_CREATED",
            user_id=getattr(g, "current_user_id", None),
            entity_type="BLOG",
            entity_id=str(blog.id),
            request=request,
        )
        session.commit()

        # Re-query with joined relationships
        blog = session.get(Blog, blog.id)
        return success(blog_to_dict(blog), status_code=201, message="Blog post created successfully")


@_admin_required
def update_blog(blog_id: int):
    """Update an existing blog post."""
    payload = request.get_json(force=True, silent=True) or {}

    with get_session() as session:
        blog = session.get(Blog, blog_id)
        if not blog:
            raise NotFoundError("Blog not found")

        if "title" in payload:
            clean_title = str(payload["title"]).strip()
            if not clean_title:
                raise ValidationError("Blog title cannot be empty")
            blog.title = clean_title

        if "introduction" in payload:
            blog.introduction = str(payload.get("introduction") or "").strip()

        if "content" in payload:
            blog.content = str(payload.get("content") or "").strip()

        field_map = {
            "image_url": "image_url",
            "imageUrl": "image_url",
            "tags": "tags",
            "meta_title": "meta_title",
            "metaTitle": "meta_title",
            "meta_description": "meta_description",
            "metaDescription": "meta_description",
            "meta_keywords": "meta_keywords",
            "metaKeywords": "meta_keywords",
            "canonical_url": "canonical_url",
            "canonicalUrl": "canonical_url",
        }
        for payload_key, model_key in field_map.items():
            if payload_key in payload:
                value = payload[payload_key]
                if model_key == "tags":
                    value = _normalize_list(value)
                elif isinstance(value, str):
                    value = value.strip() or None
                setattr(blog, model_key, value)

        if "is_pinned" in payload or "isPinned" in payload:
            blog.is_pinned = bool(payload.get("is_pinned", payload.get("isPinned")))

        if any(k in payload for k in ("author", "author_id", "authorId", "authorName")):
            author = _resolve_author(session, payload)
            blog.author_id = author.id

        if any(k in payload for k in ("category", "category_id", "categoryId", "categoryName")):
            category = _resolve_category(session, payload)
            blog.category_id = category.id

        if "status" in payload:
            blog.status = _normalize_status(payload["status"])
            blog.is_post = blog.status == "Published"

        if "date" in payload:
            blog.date = _parse_date(payload["date"])

        blog.updated_at = now_ist()
        session.flush()

        log_audit(
            session,
            action="BLOG_UPDATED",
            user_id=getattr(g, "current_user_id", None),
            entity_type="BLOG",
            entity_id=str(blog.id),
            request=request,
        )
        session.commit()

        blog = session.get(Blog, blog.id)
        return success(blog_to_dict(blog), message="Blog post updated successfully")


@_admin_required
def delete_blog(blog_id: int):
    """Delete a blog post."""
    with get_session() as session:
        blog = session.get(Blog, blog_id)
        if not blog:
            raise NotFoundError("Blog not found")
        session.delete(blog)

        log_audit(
            session,
            action="BLOG_DELETED",
            user_id=getattr(g, "current_user_id", None),
            entity_type="BLOG",
            entity_id=str(blog_id),
            request=request,
        )
        session.commit()

        return success({"deleted": True, "id": blog_id}, message="Blog post deleted successfully")


# ============================================================
# Category Master Handlers
# ============================================================
def list_categories():
    """List all categories with blog post counts."""
    with get_session() as session:
        rows = (
            session.query(CategoryMaster, func.count(Blog.id).label("blog_count"))
            .outerjoin(Blog, CategoryMaster.id == Blog.category_id)
            .group_by(CategoryMaster.id)
            .order_by(CategoryMaster.name.asc())
            .all()
        )
        data = [category_to_dict(cat, count=cnt) for cat, cnt in rows]
        return success(data, count=len(data))


@_admin_required
def create_category():
    """Create a new category."""
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["name"])
    name = str(payload["name"]).strip()

    with get_session() as session:
        existing = session.query(CategoryMaster).filter(func.lower(CategoryMaster.name) == name.lower()).first()
        if existing:
            return success(category_to_dict(existing), message="Category already exists")

        cat = CategoryMaster(name=name, is_active=True)
        session.add(cat)
        session.flush()
        return success(category_to_dict(cat), status_code=201, message="Category created successfully")


@_admin_required
def update_category(category_id: int):
    """Update a category."""
    payload = request.get_json(force=True, silent=True) or {}

    with get_session() as session:
        cat = session.get(CategoryMaster, category_id)
        if not cat:
            raise NotFoundError("Category not found")

        if "name" in payload:
            cat.name = str(payload["name"]).strip()
        if "isActive" in payload or "is_active" in payload:
            cat.is_active = bool(payload.get("isActive", payload.get("is_active")))

        cat.updated_at = now_ist()
        session.flush()
        return success(category_to_dict(cat), message="Category updated successfully")


@_admin_required
def delete_category(category_id: int):
    """Delete a category."""
    with get_session() as session:
        cat = session.get(CategoryMaster, category_id)
        if not cat:
            raise NotFoundError("Category not found")
        session.delete(cat)
        return success({"deleted": True, "id": category_id}, message="Category deleted successfully")


# ============================================================
# Author Master Handlers
# ============================================================
def list_authors():
    """List all authors with blog post counts."""
    with get_session() as session:
        rows = (
            session.query(AuthorMaster, func.count(Blog.id).label("blog_count"))
            .outerjoin(Blog, AuthorMaster.id == Blog.author_id)
            .group_by(AuthorMaster.id)
            .order_by(AuthorMaster.name.asc())
            .all()
        )
        data = [author_to_dict(author, count=cnt) for author, cnt in rows]
        return success(data, count=len(data))


@_admin_required
def create_author():
    """Create a new author."""
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["name"])
    name = str(payload["name"]).strip()

    with get_session() as session:
        existing = session.query(AuthorMaster).filter(func.lower(AuthorMaster.name) == name.lower()).first()
        if existing:
            return success(author_to_dict(existing), message="Author already exists")

        author = AuthorMaster(name=name, is_active=True)
        session.add(author)
        session.flush()
        return success(author_to_dict(author), status_code=201, message="Author created successfully")


def increment_blog_share(blog_id: int):
    """Increment share count for a blog post (public endpoint)."""
    with get_session() as session:
        blog = session.get(Blog, blog_id)
        if not blog:
            raise NotFoundError("Blog not found")
        blog.shares_count = (blog.shares_count or 0) + 1
        session.flush()
        return success({"id": blog.id, "sharesCount": blog.shares_count}, message="Share recorded successfully")

