"""Dynamic SEO Metadata Controller for EduJunction.
Manages dynamic SEO titles, descriptions, keywords, OpenGraph tags, and canonical URLs.
"""
from flask import request
from database.dbConnection import get_session, engine
from model.models import Base, SeoMetadata
from utils.errors import ValidationError, NotFoundError
from utils.response import success
from utils.logger import logger


def _ensure_seo_table():
    """Ensure seo_metadata table exists in database."""
    try:
        Base.metadata.create_all(bind=engine, tables=[SeoMetadata.__table__])
    except Exception as e:
        logger.warning(f"Could not ensure seo_metadata table: {e}")


def get_all_seo_metadata():
    """Fetch active SEO metadata items for frontend consumption & admin view."""
    _ensure_seo_table()
    try:
        with get_session() as session:
            items = session.query(SeoMetadata).all()
            if items and len(items) > 0:
                return success([
                    {
                        "id": item.id,
                        "page_route": item.page_route,
                        "page_name": item.page_name,
                        "title": item.title,
                        "description": item.description,
                        "keywords": item.keywords,
                        "og_image": item.og_image,
                        "canonical_url": item.canonical_url,
                        "is_active": item.is_active,
                        "created_at": item.created_at.isoformat() if item.created_at else None,
                        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                    }
                    for item in items
                ])
    except Exception as e:
        logger.warning(f"SeoMetadata table query error: {e}")

    # Fallback default records if table empty or DB initializing
    return success([
        {
            "id": 1,
            "page_route": "/",
            "page_name": "Home Page",
            "title": "EduJunction – AI-Powered Adaptive Learning & Board Model Papers",
            "description": "Prepare for CBSE, ICSE, ISC Board Exams with authentic 2027 Model Question Papers and instant AI evaluation.",
            "keywords": "EduJunction, CBSE model papers, ICSE model question papers, ISC board exams, class 10 mock test",
            "og_image": "https://www.edujunction.co.in/og-banner.png",
            "canonical_url": "https://www.edujunction.co.in/",
            "is_active": True,
        },
        {
            "id": 2,
            "page_route": "/about",
            "page_name": "About Us",
            "title": "About Us – EduJunction | Next-Gen AI Learning Platform",
            "description": "Learn about EduJunction's mission to revolutionize board exam preparation with adaptive AI and diagnostic analytics.",
            "keywords": "EduJunction about, AI learning, edtech platform",
            "og_image": "https://www.edujunction.co.in/og-banner.png",
            "canonical_url": "https://www.edujunction.co.in/about",
            "is_active": True,
        },
        {
            "id": 3,
            "page_route": "/blog",
            "page_name": "Blog Hub",
            "title": "EdTech & Board Exam Insights – EduJunction Blog",
            "description": "Latest insights, study tips, exam strategies, and educational updates for CBSE, ICSE, and ISC students.",
            "keywords": "EduJunction blog, board exam tips, study strategies",
            "og_image": "https://www.edujunction.co.in/og-banner.png",
            "canonical_url": "https://www.edujunction.co.in/blog",
            "is_active": True,
        },
        {
            "id": 4,
            "page_route": "/contact",
            "page_name": "Contact Us",
            "title": "Contact Us – EduJunction Support & Helpdesk",
            "description": "Get in touch with EduJunction for school integration, parent inquiries, and student support.",
            "keywords": "EduJunction contact, support, edtech help",
            "og_image": "https://www.edujunction.co.in/og-banner.png",
            "canonical_url": "https://www.edujunction.co.in/contact",
            "is_active": True,
        }
    ])


def save_seo_metadata():
    """Create or update SEO metadata record."""
    _ensure_seo_table()
    data = request.get_json() or {}
    page_route = (data.get("page_route") or "").strip()
    page_name = (data.get("page_name") or "").strip()
    title = (data.get("title") or "").strip()

    if not page_route or not page_name or not title:
        raise ValidationError("Page route, page name, and SEO title are required.")

    item_id = data.get("id")

    with get_session() as session:
        if item_id:
            item = session.query(SeoMetadata).filter(SeoMetadata.id == item_id).first()
            if not item:
                raise NotFoundError("SEO metadata item not found.")
        else:
            item = session.query(SeoMetadata).filter(SeoMetadata.page_route == page_route).first()
            if not item:
                item = SeoMetadata(page_route=page_route)
                session.add(item)

        item.page_route = page_route
        item.page_name = page_name
        item.title = title
        item.description = (data.get("description") or "").strip()
        item.keywords = (data.get("keywords") or "").strip()
        item.og_image = (data.get("og_image") or "").strip()
        item.canonical_url = (data.get("canonical_url") or "").strip()
        item.is_active = bool(data.get("is_active", True))

        session.commit()
        return success({
            "id": item.id,
            "page_route": item.page_route,
            "page_name": item.page_name,
            "title": item.title,
            "description": item.description,
            "keywords": item.keywords,
            "og_image": item.og_image,
            "canonical_url": item.canonical_url,
            "is_active": item.is_active,
        }, message="SEO metadata saved successfully.")


def delete_seo_metadata(seo_id: int):
    """Delete SEO metadata record."""
    _ensure_seo_table()
    with get_session() as session:
        item = session.query(SeoMetadata).filter(SeoMetadata.id == seo_id).first()
        if not item:
            raise NotFoundError("SEO metadata item not found.")
        session.delete(item)
        session.commit()
        return success({"id": seo_id}, message="SEO metadata item deleted.")
