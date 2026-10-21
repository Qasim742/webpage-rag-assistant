from pydantic import BaseModel, Field, HttpUrl


class ProcessPageRequest(BaseModel):
    url: HttpUrl
    title: str = Field(default="", max_length=512)
    content: str | None = Field(default=None, max_length=500_000)
    refresh: bool = False


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    url: HttpUrl | None = None


class HomeResponse(BaseModel):
    message: str


class ProcessPageResponse(BaseModel):
    message: str
    url: HttpUrl
    documents: int
    chunks: int
    vectors: int


class ChatResponse(BaseModel):
    answer: str