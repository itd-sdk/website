"""Top hashtags of posts and comments"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import text

from app.services.db import Session, get_db
from app.services.limiter import get_limiter

router = APIRouter(prefix="/hashtags")

# uppercase cyrillic is mapped by hand, lower() depends on the database locale
HASHTAGS_SQL = """
    select tag, count(distinct id) as count
    from (
        select id, translate(
            lower((regexp_matches(content, :pattern, 'g'))[2]),
            'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ',
            'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'
        ) as tag
        from {table}
        where exists and content like '%#%'
    ) tags
    group by tag
    order by count desc
    limit 5000
"""
# a tag starts after a space or punctuation, not inside a word or a url path,
# the same rule as the highlighting on the page
HASHTAG_PATTERN = "(^|[^0-9A-Za-zА-Яа-яЁё_/#])#([0-9A-Za-zА-Яа-яЁё_]+)"
CACHE_TTL = timedelta(hours=1)


class HashtagResponse(BaseModel):
    tag: str
    posts: int  # posts with the tag
    comments: int  # comments with the tag


counts: dict[str, dict[str, int]] = {}
counts_updated_at = datetime.min


def get_counts(db: Session) -> dict[str, dict[str, int]]:
    # both tables are counted once an hour, the comments checkbox only re-ranks
    global counts, counts_updated_at
    if datetime.now() - counts_updated_at > CACHE_TTL:
        counts = {
            table: dict(
                db.execute(
                    text(HASHTAGS_SQL.format(table=table)), {"pattern": HASHTAG_PATTERN}
                ).all()
            )
            for table in ("posts", "comments")
        }
        counts_updated_at = datetime.now()
    return counts


@router.get("", response_model=list[HashtagResponse])
@get_limiter().limit("30/minute")
def api_get_ebdi_hashtags(
    request: Request,
    comments: bool = False,  # rank by posts and comments together
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    data = get_counts(db)
    posts, in_comments = data["posts"], data["comments"]
    tags = set(posts) | set(in_comments) if comments else set(posts)
    rows = [
        HashtagResponse(
            tag=tag, posts=posts.get(tag, 0), comments=in_comments.get(tag, 0)
        )
        for tag in tags
    ]

    def score(row: HashtagResponse) -> int:
        return row.posts + row.comments if comments else row.posts

    rows.sort(key=lambda row: (-score(row), row.tag))
    return rows[:limit]
