from functools import wraps
from inspect import signature

AUTO_LANGUAGE = "auto"
AUTO_LANGUAGE_INSTRUCTION = (
    "the language requested explicitly by the user; otherwise use the language "
    "of the user's current question"
)


def configure_auto_language(page):
    from ktem.utils import SUPPORTED_LANGUAGE_MAP

    SUPPORTED_LANGUAGE_MAP[AUTO_LANGUAGE] = AUTO_LANGUAGE_INSTRUCTION
    page.language.choices = [("自动判断", AUTO_LANGUAGE)] + [
        choice for choice in page.language.choices if choice[1] != AUTO_LANGUAGE
    ]
    page.language.value = AUTO_LANGUAGE
    page.language.visible = False
    original = page.create_pipeline
    if getattr(original, "_automatic_language", False):
        return
    call_signature = signature(original)

    @wraps(original)
    def create_pipeline(*args, **kwargs):
        arguments = call_signature.bind(*args, **kwargs)
        arguments.arguments["session_language"] = AUTO_LANGUAGE
        return original(*arguments.args, **arguments.kwargs)

    create_pipeline._automatic_language = True
    page.create_pipeline = create_pipeline
