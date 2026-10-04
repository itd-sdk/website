"""Ebdi websocket protocol shared by the server and the scraper client.

Keep this module free of app imports (stdlib + pydantic only), the client
uses a copy of this file. Bump PROTOCOL_VERSION on every incompatible change,
the server refuses clients with a different version.
"""

from datetime import datetime
from enum import Enum, IntEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter, field_validator

PROTOCOL_VERSION = 2


class CloseCode(IntEnum):
    invalid_token = 3003
    timeout = 3008
    task_exists = 4000
    outdated_client = 4001


class TaskType(str, Enum):
    update = "update"
    create = "create"
    posts = "posts"


class ClientMessageType(str, Enum):
    task = "task"
    update = "update"
    create = "create"
    known = "known"
    post = "post"
    posts_done = "posts_done"


class ServerMessageType(str, Enum):
    task = "task"
    updated = "updated"
    created = "created"
    known = "known"
    post_saved = "post_saved"
    posts_updated = "posts_updated"
    error = "error"


# data


class UserBody(BaseModel):
    username: str
    display_name: str
    followers_count: int
    following_count: int
    posts_count: int
    verified: bool
    avatar: str
    bio: str | None = None
    banner: str | None = None
    last_seen: str | None = None

    @field_validator("avatar")
    @classmethod
    def normalize_avatar(cls, value: str) -> str:
        return value.replace("︎", "").replace("️", "")


class NewUserBody(UserBody):
    user_id: UUID
    created_at: datetime | None = None


class CommentBody(BaseModel):
    comment_id: UUID
    author_id: UUID
    reply_to_id: UUID | None = None  # user being replied to
    created_at: datetime | None = None
    content: str = ""
    attachments: list[dict] = []
    likes_count: int = 0
    replies: list["CommentBody"] = []


class PostBody(BaseModel):
    post_id: UUID
    author_id: UUID
    created_at: datetime | None = None
    edited_at: datetime | None = None
    content: str = ""
    spans: list[dict] = []
    attachments: list[dict] = []
    likes_count: int = 0
    comments_count: int = 0
    views_count: int = 0
    poll_question: str | None = None
    poll_options: list[str] | None = None
    poll_multiple: bool | None = None
    dominant: str | None = None
    original_post_id: UUID | None = None
    wall_recipient_id: UUID | None = None
    comments: list[CommentBody] = []


class UpdateTarget(BaseModel):
    id: UUID


class PostsTarget(BaseModel):
    id: UUID
    username: str
    since: datetime | None  # send posts created after it, None means all posts


# client -> server


class TaskRequest(BaseModel):
    type: Literal[ClientMessageType.task] = ClientMessageType.task


class UpdateRequest(BaseModel):
    type: Literal[ClientMessageType.update] = ClientMessageType.update
    target_id: UUID
    target: UserBody | None  # None if the user does not exist anymore


class CreateRequest(BaseModel):
    type: Literal[ClientMessageType.create] = ClientMessageType.create
    target: NewUserBody


class KnownRequest(BaseModel):
    type: Literal[ClientMessageType.known] = ClientMessageType.known
    target_ids: list[UUID]


class PostRequest(BaseModel):
    type: Literal[ClientMessageType.post] = ClientMessageType.post
    target_id: UUID
    post: PostBody


class PostsDoneRequest(BaseModel):
    type: Literal[ClientMessageType.posts_done] = ClientMessageType.posts_done
    target_id: UUID


ClientMessage = Annotated[
    TaskRequest
    | UpdateRequest
    | CreateRequest
    | KnownRequest
    | PostRequest
    | PostsDoneRequest,
    Field(discriminator="type")
]
client_message = TypeAdapter(ClientMessage)


# server -> client


class UpdateTaskResponse(BaseModel):
    type: Literal[ServerMessageType.task] = ServerMessageType.task
    task_type: Literal[TaskType.update] = TaskType.update
    targets: list[UpdateTarget]


class CreateTaskResponse(BaseModel):
    type: Literal[ServerMessageType.task] = ServerMessageType.task
    task_type: Literal[TaskType.create] = TaskType.create
    prefix: str


class PostsTaskResponse(BaseModel):
    type: Literal[ServerMessageType.task] = ServerMessageType.task
    task_type: Literal[TaskType.posts] = TaskType.posts
    target: PostsTarget


TaskResponse = Annotated[
    UpdateTaskResponse | CreateTaskResponse | PostsTaskResponse,
    Field(discriminator="task_type")
]


class UpdatedResponse(BaseModel):
    type: Literal[ServerMessageType.updated] = ServerMessageType.updated


class CreatedResponse(BaseModel):
    type: Literal[ServerMessageType.created] = ServerMessageType.created


class KnownResponse(BaseModel):
    type: Literal[ServerMessageType.known] = ServerMessageType.known
    user_ids: list[UUID]


class PostSavedResponse(BaseModel):
    type: Literal[ServerMessageType.post_saved] = ServerMessageType.post_saved


class PostsUpdatedResponse(BaseModel):
    type: Literal[ServerMessageType.posts_updated] = ServerMessageType.posts_updated


class ErrorResponse(BaseModel):
    type: Literal[ServerMessageType.error] = ServerMessageType.error
    detail: str


ServerMessage = Annotated[
    TaskResponse
    | UpdatedResponse
    | CreatedResponse
    | KnownResponse
    | PostSavedResponse
    | PostsUpdatedResponse
    | ErrorResponse,
    Field(discriminator="type")
]
server_message = TypeAdapter(ServerMessage)
