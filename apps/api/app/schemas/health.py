from pydantic import BaseModel


class HealthDependency(BaseModel):
    name: str
    status: str


class HealthResponse(BaseModel):
    status: str
    version: str
    dependencies: list[HealthDependency]
