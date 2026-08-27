from pydantic import BaseModel


class QuestionRequest(BaseModel):
    question: str


class ClarificationItemModel(BaseModel):
    kind: str
    text: str


class AnswerRequest(BaseModel):
    question: str
    items: list[ClarificationItemModel]
    answers: list[str]


class CitationModel(BaseModel):
    label: str
    text: str


class ResultResponse(BaseModel):
    status: str
    text: str
    citations: list[CitationModel] | None = None


class NeedsClarificationResponse(BaseModel):
    status: str
    question: str
    items: list[ClarificationItemModel]
