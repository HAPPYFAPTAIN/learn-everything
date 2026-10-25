from functools import wraps
from inspect import signature
import logging

import gradio as gr

from learning_ext.local_embeddings import LocalEmbeddingUnavailable


_LOG = logging.getLogger(__name__)
_MARKER = '<!-- le-chat-interrupted -->'
_RETRY = '你的问题和参考资料已保留，恢复连接后可以重新发送。'


def _failed(history):
    return bool(history and isinstance(history[-1][1], str) and _MARKER in history[-1][1])


def _message(error):
    if isinstance(error, LocalEmbeddingUnavailable):
        return str(error)
    kind = type(error).__name__.lower()
    if any(part in kind for part in ('authentication', 'permission')):
        return '模型连接未获授权，请在「模型配置」检查密钥和模型权限。'
    if any(part in kind for part in ('timeout', 'connection', 'retry')):
        return '模型或资料检索服务暂时无法连接，请检查服务是否已启动。'
    return '这次回答没有完成，请检查模型与资料检索配置后重试。'


def configure_chat_recovery(page):
    original = page.chat_fn
    if getattr(original, '_learning_recovery', False):
        return
    call_signature = signature(original)

    @wraps(original)
    def chat(*args, **kwargs):
        bound = call_signature.bind(*args, **kwargs)
        latest = None
        iterator = None
        try:
            iterator = original(*args, **kwargs)
            for latest in iterator:
                yield latest
        except Exception as error:
            history = latest[0] if isinstance(latest, tuple) and len(latest) == 5 else bound.arguments.get('chat_history')
            if not history:
                raise
            history = list(history)
            question, partial = history[-1]
            if not isinstance(partial, str) or partial.strip().lower() in ('thinking ...', 'thinking…', 'thinking...', '') or _MARKER in partial:
                partial = ''
            notice = f'{_MARKER}**回答暂时中断**\n\n{_message(error)}\n\n{_RETRY}'
            history[-1] = (question, f'{partial}\n\n---\n\n{notice}' if partial else notice)
            state = latest[4] if isinstance(latest, tuple) and len(latest) == 5 else bound.arguments.get('chat_state')
            refs = latest[1] if partial and isinstance(latest, tuple) else ''
            _LOG.warning('chat_interrupted type=%s', type(error).__name__)
            yield history, refs, gr.update(visible=False), None, state
        finally:
            close = getattr(iterator, 'close', None)
            if close:
                try:
                    close()
                except Exception as error:
                    _LOG.warning('chat_cleanup_failed type=%s', type(error).__name__)

    chat._learning_recovery = True
    page.chat_fn = chat
    name_conversation = page.check_and_suggest_name_conv
    suggest = page.suggest_chat_conv

    @wraps(name_conversation)
    def name(history):
        if _failed(history):
            return gr.update(), False
        return name_conversation(history)

    @wraps(suggest)
    def suggestions(settings, session_language, chat_history, use_suggestion):
        if _failed(chat_history):
            return gr.update(visible=False), []
        return suggest(settings, session_language, chat_history, use_suggestion)

    page.check_and_suggest_name_conv = name
    page.suggest_chat_conv = suggestions
