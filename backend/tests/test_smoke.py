from fastapi import FastAPI

from app.main import app


def test_app_is_fastapi_instance():
    assert isinstance(app, FastAPI)


def test_app_title_is_set():
    assert app.title == "LLM Programming Tutor"
