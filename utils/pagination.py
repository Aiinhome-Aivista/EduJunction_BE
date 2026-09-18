from flask import request


def get_pagination_params(default_limit: int = 20, max_limit: int = 100):
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        limit = int(request.args.get("limit", default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    limit = max(1, min(limit, max_limit))
    offset = (page - 1) * limit
    return page, limit, offset


def paginated_response(items: list, total: int, page: int, limit: int):
    return {
        "items": items,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "totalPages": (total + limit - 1) // limit if limit else 0,
        },
    }
