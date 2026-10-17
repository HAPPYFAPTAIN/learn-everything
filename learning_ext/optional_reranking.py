from functools import wraps


def missing_service_credentials(spec):
    vendor = spec.get("__type__", "")
    if vendor not in ("kotaemon.rerankings.CohereReranking", "kotaemon.rerankings.VoyageAIReranking"):
        return False
    key = str(spec.get("api_key") or "").strip()
    return not key or key.startswith("placeholder-")


def configure_optional_reranking():
    from ktem.index.file.pipelines import DocumentRetrievalPipeline
    from ktem.rerankings.manager import reranking_models_manager as manager

    original = DocumentRetrievalPipeline.get_pipeline.__func__
    if getattr(original, "_optional_credentials", False):
        return

    @wraps(original)
    def get_pipeline(cls, user_settings, index_settings, selected):
        name = index_settings.get("reranking", manager.get_default_name())
        spec = manager.info().get(name, {}).get("spec", {})
        if missing_service_credentials(spec):
            user_settings = dict(user_settings, use_reranking=False)
        return original(cls, user_settings, index_settings, selected)

    get_pipeline._optional_credentials = True
    DocumentRetrievalPipeline.get_pipeline = classmethod(get_pipeline)
