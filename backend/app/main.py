from fastapi import FastAPI

from app.core.errors import install_exception_handlers
from app.core.responses import install_request_id

app = FastAPI(title="LLM Programming Tutor")

install_request_id(app)
install_exception_handlers(app)
