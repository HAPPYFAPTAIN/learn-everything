"""极简模型配置页 - 替代 Kotaemon 复杂的 Resources 页。

用户只需：选服务商 → 填 API Key → 点保存。
后台自动填好 base_url / 模型名，并即时更新运行时 LLM 池。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from learning_ext.page_design import page_intro
import gradio as gr
from ktem.app import BasePage

logger = logging.getLogger(__name__)

from html import escape
from learning_ext import connection_store as connections
from learning_ext.model_platforms import (
    PLATFORMS, detect_platform, profile_for, platform_draft, origin,
    connection_error, is_local_ollama, request_key, model_ids,
    platform_filter_html, platform_icon_url, models_url, compatible_model, adapt_chat_params,
)


# .env 文件路径
ENV_FILE = Path(__file__).resolve().parent.parent.parent / "kotaemon" / ".env"


def _read_env() -> dict:
    """读取当前 .env 里的 LLM 配置"""
    data = {
        "base_url": "",
        "api_key": "",
        "chat_model": "",
        "embed_model": "",
    }
    if not ENV_FILE.exists():
        return data
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("OPENAI_API_BASE="):
            data["base_url"] = line.split("=", 1)[1].strip()
        elif line.startswith("OPENAI_API_KEY="):
            val = line.split("=", 1)[1].strip()
            # 过滤占位符
            if val and "请在UI" not in val and "YOUR" not in val:
                data["api_key"] = val
        elif line.startswith("OPENAI_CHAT_MODEL="):
            data["chat_model"] = line.split("=", 1)[1].strip()
        elif line.startswith("OPENAI_EMBEDDINGS_MODEL="):
            data["embed_model"] = line.split("=", 1)[1].strip()
    return data


def _write_env(updates: dict) -> None:
    """更新 .env 里指定字段 (保留其他行)"""
    if not ENV_FILE.exists():
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        ENV_FILE.write_text("", encoding="utf-8")
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    keys = {
        "base_url": "OPENAI_API_BASE",
        "api_key": "OPENAI_API_KEY",
        "chat_model": "OPENAI_CHAT_MODEL",
        "embed_model": "OPENAI_EMBEDDINGS_MODEL",
    }
    written = set()
    new_lines = []
    for line in lines:
        updated_line = line
        for field, env_key in keys.items():
            if field in updates and line.strip().startswith(env_key + "="):
                updated_line = f"{env_key}={updates[field]}"
                written.add(field)
                break
        new_lines.append(updated_line)
    # 补未找到的字段
    for field, env_key in keys.items():
        if field in updates and field not in written:
            new_lines.append(f"{env_key}={updates[field]}")
    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _apply_to_runtime(
    base_url: str, api_key: str, chat_model: str, embed_model: str
) -> str:
    """即时更新运行时 LLM 池 (无需重启)"""
    try:
        from ktem.llms.manager import llms

        chat_spec = {
            "__type__": "kotaemon.llms.ChatOpenAI",
            "temperature": 0.3,
            "base_url": base_url,
            "api_key": api_key,
            "model": chat_model,
            "timeout": 60,
        }
        if "openai" in llms:
            llms.update("openai", spec=chat_spec, default=True)
        else:
            llms.add("openai", spec=chat_spec, default=True)

        # embedding 仅在有值时更新
        from learning_ext.local_embeddings import local_embedding_active
        if embed_model and not local_embedding_active():
            embed_spec = {
                "__type__": "kotaemon.embeddings.OpenAIEmbeddings",
                "base_url": base_url,
                "api_key": api_key,
                "model": embed_model,
                "timeout": 30,
            }
            try:
                from ktem.embeddings.manager import (
                    embedding_models_manager as embeddings,
                )

                if "openai" in embeddings:
                    embeddings.update("openai", spec=embed_spec, default=True)
                else:
                    embeddings.add("openai", spec=embed_spec, default=True)
            except Exception as e:
                logger.exception("向量模型配置未生效")
                return "对话模型已更新，但资料检索模型未能启用。请检查向量模型配置。"

        return "ok"
    except Exception as e:
        logger.exception("运行时更新失败")
        return f"运行时更新失败: {e}"


def _test_llm(base_url: str, api_key: str, chat_model: str) -> tuple[str, str]:
    """发一个测试请求验证配置"""
    error = connection_error(base_url, api_key, chat_model)
    if error:
        return error, ""
    api_key = request_key(base_url, api_key)
    try:
        import requests

        payload = adapt_chat_params(base_url, {
            "model": chat_model,
            "messages": [{"role": "user", "content": "只回复两个字：你好"}],
            ("max_completion_tokens" if origin(base_url)[1] == "api.openai.com" else "max_tokens"): 4096,
            **({"reasoning_effort": "low"} if chat_model.lower().startswith("glm-5.3") else {}),
        })
        extra_headers = payload.pop("extra_headers", {})

        resp = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                **extra_headers,
            },
            json=payload,
            timeout=60,
            allow_redirects=False,
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            if not content or not content.strip():
                return "模型已响应，但没有返回正文。请检查模型参数或稍后重试。", ""
            return f"连接成功 · {content}", content
        else:
            explanations = {
                401: "密钥未通过验证。请检查是否复制完整，或到服务商页面确认密钥有效。",
                403: "当前账号没有访问这个模型的权限。请检查模型名称和账号权限。",
                404: "没有找到这个接口或模型。请检查高级连接设置中的地址与模型名称。",
                429: "服务商暂时限制了请求，或账号额度不足。请稍后重试并检查可用额度。",
            }
            return explanations.get(resp.status_code, f"模型服务暂时未完成请求（HTTP {resp.status_code}）。你填写的内容还在，可以稍后重新测试。"), ""
    except requests.exceptions.ProxyError:
        return "暂时连不上代理服务。你填写的内容还在，请检查代理是否运行，再点“测试连接”。", ""
    except requests.exceptions.Timeout:
        return "连接等待超时。你填写的内容还在，可以稍后重新测试。", ""
    except requests.exceptions.ConnectionError:
        return "暂时连不上模型服务。请检查网络与接口地址，再点“测试连接”。", ""
    except Exception:
        logger.warning("模型连接测试未能解析响应", exc_info=True)
        return "服务返回了无法识别的结果。请检查接口是否支持 OpenAI 兼容格式。", ""


def _fetch_models(base_url, api_key, current):
    public_catalog = origin(base_url)[1] == "opencode.ai"
    error = connection_error(base_url, "public-catalog" if public_catalog else api_key)
    if error:
        return gr.update(), error
    import requests
    try:
        headers = {"User-Agent":"LearnEverything/1.0"}
        if not public_catalog:
            headers["Authorization"] = f"Bearer {request_key(base_url, api_key)}"
        response = requests.get(
            models_url(base_url),
            headers=headers,
            timeout=20, allow_redirects=False,
        )
        if response.status_code != 200:
            return gr.update(), "暂时无法读取模型列表，可以直接填写模型 ID。"
        choices = [model for model in model_ids(response.json()) if compatible_model(base_url, model)]
        if not choices:
            return gr.update(), "未找到对话模型，可以直接填写模型 ID。"
        if current and current not in choices:
            choices.insert(0, current)
        return gr.update(choices=choices, value=current or None), f"已读取 {len(choices)} 个模型，选择后测试连接。"
    except (requests.exceptions.RequestException, ValueError, TypeError):
        return gr.update(), "未能读取模型列表，请检查连接，或直接填写模型 ID。"


class QuickSetupPage(BasePage):
    def on_building_ui(self):
        gr.HTML(page_intro("setup"))
        current = _read_env()
        provider = detect_platform(current["base_url"]) if current["base_url"] else "deepseek"
        storage_error = ""
        try:
            connections.remember(provider, current, only_if_missing=True)
            saved_choices = connections.connection_choices(current)
        except Exception:
            saved_choices = []
            storage_error = "无法读取本机保存的连接。当前连接仍可使用，请检查 Windows 账户或文件权限。"
        draft = platform_draft(provider, current)
        self.saved = gr.State(current)
        self.draft_provider = gr.State(provider)
        self.endpoint_origin = gr.State(origin(draft["base_url"]))
        cfg = PLATFORMS[provider]
        profile = profile_for(provider, draft["base_url"])
        with gr.Row(elem_id="le-platform-layout"):
            with gr.Column(scale=1, min_width=240, elem_id="le-platform-directory"):
                gr.HTML('<h2>选择平台</h2>')
                gr.HTML(platform_filter_html())
                self.provider = gr.Radio(
                    choices=[(item["name"], key) for key, item in PLATFORMS.items()],
                    value=provider, label="模型平台", show_label=False,
                    elem_id="le-platform-picker",
                )
            with gr.Column(scale=3, min_width=320, elem_id="le-settings-form"):
                self.saved_connection = gr.Dropdown(
                    choices=saved_choices, value=connections.connection_id(provider, current["base_url"]) if saved_choices and any(v == connections.connection_id(provider, current["base_url"]) for _, v in saved_choices) else None,
                    label="我的连接", elem_id="le-my-connections",
                )
                self.remember_status = gr.Markdown(storage_error, elem_id="le-remember-status")
                self.platform_heading = gr.HTML(self._platform_heading(provider))
                self.api_key = gr.Textbox(
                    label="连接密钥", placeholder="粘贴 API Key",
                    value=draft["api_key"], type="password", lines=1,
                    visible=not is_local_ollama(draft["base_url"]),
                )
                self.key_link = gr.HTML(self._key_link(provider, draft["base_url"]))
                with gr.Row(elem_id="le-model-choice-row"):
                    self.chat_model = gr.Dropdown(
                        label="对话模型", choices=list(dict.fromkeys([*cfg["models"], *([draft["chat_model"]] if draft["chat_model"] else [])])),
                        value=draft["chat_model"] or None, allow_custom_value=True,
                    )
                    self.fetch_btn = gr.Button("刷新模型 ↻", elem_id="le-fetch-models", size="sm", scale=0)
                self.model_status = gr.Markdown("", elem_id="le-model-fetch-status")
                with gr.Accordion("连接与检索设置", open=False, elem_id="le-connection-advanced"):
                    self.profile = gr.Dropdown(
                        choices=list(dict.fromkeys([*cfg["profiles"], "自定义地址"])),
                        value=profile, label="服务方案" if provider == "opencode" else "接口区域", visible=len(cfg["profiles"]) > 1 or profile == "自定义地址",
                        filterable=False,
                    )
                    with gr.Accordion("连接地址", open=profile == "自定义地址", elem_id="le-endpoint-options") as self.address_options:
                        self.base_url = gr.Textbox(label="服务地址", value=draft["base_url"], placeholder="https://…/v1", lines=1)
                    with gr.Accordion("资料检索", open=False, elem_id="le-embedding-options"):
                        gr.Markdown("对话与资料检索可分别配置。切换对话平台不会改动已启用的本地检索。")
                        self.embed_model = gr.Textbox(label="同一接口下的向量模型 · 选填", value=draft["embed_model"], placeholder="填写模型 ID，或使用下方本地检索", lines=1)
                        self.local_embed_model = gr.Textbox(label="Ollama 本地向量模型", value="qwen3-embedding:4b", lines=1)
                        self.local_embed_enable = gr.Button("测试并启用本地检索", size="sm")
                        self.local_embed_status = gr.Markdown("")
                    with gr.Accordion("平台使用说明", open=False, elem_id="le-platform-help"):
                        self.note = gr.Markdown(cfg["note"], elem_id="le-platform-note")
                with gr.Row(elem_classes=["le-action-bar"]):
                    self.test_btn = gr.Button("测试连接", variant="secondary")
                    self.remember_btn = gr.Button("保存连接", variant="secondary")
                    self.save_btn = gr.Button("启用连接", variant="primary")
                self.result = gr.Markdown("", elem_id="le-connection-result")
                self.status_display = gr.HTML(self._build_status(current), elem_id="le-saved-connection")
                gr.HTML('<div class="le-connection-return"><button type="button" data-le-nav="learning-guide-tab">返回学习首页 →</button></div>')

    @staticmethod
    def _platform_heading(provider):
        cfg = PLATFORMS[provider]
        return f'<div class="le-platform-heading"><span class="le-platform-mark"><img src="{platform_icon_url(provider)}" alt="" width="36" height="36"></span><div><span>{cfg["tag"]}</span><h2>{cfg["name"]}</h2></div><span class="le-connection-badge">连接设置</span></div>'

    @staticmethod
    def _key_link(provider, base_url=""):
        cfg = PLATFORMS[provider]
        if origin(base_url)[1] == "api.minimax.io":
            cfg = {**cfg, "key_url":"https://platform.minimax.io/", "docs":"https://platform.minimax.io/docs/api-reference/text-openai-api"}
        elif origin(base_url)[1] == "api.moonshot.ai":
            cfg = {**cfg, "key_url":"https://platform.kimi.ai/", "docs":"https://platform.kimi.ai/docs/guide/migrating-from-openai-to-kimi"}
        links = []
        if cfg["key_url"]:
            links.append(f'<a href="{cfg["key_url"]}" target="_blank" rel="noopener noreferrer">获取 API Key ↗</a>')
        if cfg["docs"]:
            links.append(f'<a href="{cfg["docs"]}" target="_blank" rel="noopener noreferrer">接入文档 ↗</a>')
        return '<div class="le-platform-links">' + ''.join(links) + '</div>'

    @staticmethod
    def _build_status(current):
        from learning_ext.local_embeddings import local_embedding_active
        model = current.get("chat_model", "")
        configured = bool(current.get("api_key") and model)
        provider = PLATFORMS[detect_platform(current.get("base_url", ""))]["name"]
        retrieval = "本地检索已启用" if local_embedding_active() else ("已配置向量模型" if current.get("embed_model") else "资料检索未配置")
        title = "当前启用" if configured else "尚未启用连接"
        detail = f'{escape(provider)} · {escape(model)}' if configured else "选好平台后，验证并启用。"
        return f'<div class="le-saved-summary"><span class="le-saved-dot"></span><div><strong>{title}</strong><p>{detail}</p></div><span>{retrieval}</span></div>'

    def _provider_changed(self, provider, saved):
        cfg = PLATFORMS[provider]
        draft = saved if saved.get("_selected") else (connections.find_connection(provider=provider) or platform_draft(provider, saved))
        profile = profile_for(provider, draft["base_url"])
        choices = list(dict.fromkeys([*cfg["models"], *([draft["chat_model"]] if draft["chat_model"] else [])]))
        return (
            gr.update(choices=list(dict.fromkeys([*cfg["profiles"], "自定义地址"])), value=profile, label="服务方案" if provider == "opencode" else "接口区域", visible=len(cfg["profiles"]) > 1 or profile == "自定义地址"),
            draft["base_url"], gr.update(choices=choices, value=draft["chat_model"] or None),
            gr.update(value=draft["api_key"], visible=not is_local_ollama(draft["base_url"])),
            draft["embed_model"], self._platform_heading(provider), cfg["note"], self._key_link(provider, draft["base_url"]),
            gr.update(open=profile == "自定义地址"), origin(draft["base_url"]), "", "",
        )

    def _remember(self, provider, key, url, model, embed):
        config = dict(api_key=key, base_url=url, chat_model=model, embed_model=embed)
        try:
            record_id = connections.remember(provider, config)
            if not record_id:
                return gr.update(), "填好连接地址和密钥后即可保存。"
            return gr.update(choices=connections.connection_choices(_read_env()), value=record_id), "已记住此连接 · 仅保存在本机"
        except Exception:
            return gr.update(), "连接未能保存，请检查本机存储权限。填写的内容仍保留在页面中。"

    def _switch_provider(self, provider, previous, key, url, model, embed, saved):
        picker, message = self._remember(previous, key, url, model, embed)
        try:
            result = self._provider_changed(provider, saved)
            record = connections.find_connection(provider=provider)
            picker = gr.update(choices=connections.connection_choices(_read_env()), value=record["id"] if record else None)
        except Exception:
            result = self._provider_changed(provider, {**platform_draft(provider, saved), "_selected": True})
            message = "暂时无法读取已保存的连接，请检查本机存储权限。"
        return (*result, provider, picker, message if "未能" in message or "无法" in message else "")

    def _select_connection(self, record_id, previous, key, url, model, embed):
        try:
            record = connections.find_connection(record_id=record_id) if record_id else None
            if not record:
                return (*([gr.update()] * 14), "请选择已保存的连接。")
            self._remember(previous, key, url, model, embed)
            provider = record["provider"]
            return (*self._provider_changed(provider, {**record, "_selected": True}), provider, provider, "")
        except Exception:
            return (*([gr.update()] * 14), "无法读取此连接，请检查本机存储权限。")

    def _save(self, api_key, base_url, chat_model, embed_model, provider=None):
        current = _read_env()
        model = (chat_model or "").strip()
        error = connection_error(base_url, api_key, model)
        if error:
            return error, self._build_status(current), current
        base_url = base_url.strip().rstrip("/")
        api_key = request_key(base_url, api_key)
        embed_model = embed_model.strip()
        if any(c in embed_model for c in "\r\n"):
            return "向量模型名称不能包含换行。", self._build_status(current), current
        provider = provider or detect_platform(base_url)
        updated = dict(base_url=base_url, api_key=api_key, chat_model=model, embed_model=embed_model)
        try:
            record = connections.find_connection(provider=provider, base_url=base_url)
            validated = record and record.get("verified") and all(record.get(k) == v for k, v in updated.items())
        except Exception:
            validated = False
        msg, reply = ("", "verified") if validated else _test_llm(base_url, api_key, model)
        if not reply:
            return msg + " 当前启用的连接保持不变。", self._build_status(current), current
        try:
            connections.remember(provider, updated, verified=True)
            _write_env(updated)
            from learning_ext.llm.client import invalidate_cache
            invalidate_cache()
            result = _apply_to_runtime(base_url, api_key, model, embed_model)
            if result != "ok":
                return "连接验证通过，配置已保存；部分运行设置未更新，请重启后检查。", self._build_status(updated), updated
            return "连接已启用，可以开始学习了。", self._build_status(updated), updated
        except Exception:
            logger.exception("保存连接失败")
            actual = _read_env()
            return "保存未完成，请重试。", self._build_status(actual), actual

    def on_register_events(self):
        from learning_ext.local_embeddings import configure_local_embeddings
        self.local_embed_enable.click(configure_local_embeddings, inputs=[self.local_embed_model], outputs=[self.local_embed_status])
        self.provider.input(
            self._switch_provider, [self.provider, self.draft_provider, self.api_key, self.base_url, self.chat_model, self.embed_model, self.saved],
            [self.profile, self.base_url, self.chat_model, self.api_key, self.embed_model, self.platform_heading, self.note, self.key_link, self.address_options, self.endpoint_origin, self.result, self.model_status, self.draft_provider, self.saved_connection, self.remember_status],
            show_progress="hidden",
        )
        self.saved_connection.input(
            self._select_connection,
            [self.saved_connection,self.draft_provider,self.api_key,self.base_url,self.chat_model,self.embed_model],
            [self.profile,self.base_url,self.chat_model,self.api_key,self.embed_model,self.platform_heading,self.note,self.key_link,self.address_options,self.endpoint_origin,self.result,self.model_status,self.provider,self.draft_provider,self.remember_status],
            show_progress="hidden",
        )
        def change_profile(provider, profile, base, key, model, embed):
            picker, message = self._remember(provider, key, base, model, embed)
            url = PLATFORMS[provider]["profiles"].get(profile, base)
            try:
                record = connections.find_connection(provider=provider, base_url=url)
                if record:
                    key, model, embed = record["api_key"], record["chat_model"], record["embed_model"]
                elif url != base:
                    key, model, embed = "", (PLATFORMS[provider]["models"] or [None])[0], ""
                picker = gr.update(choices=connections.connection_choices(_read_env()), value=record["id"] if record else None)
            except Exception:
                key = key if url == base else ""
                message = "无法读取已保存的连接。"
            choices = list(dict.fromkeys([*PLATFORMS[provider]["models"], *([model] if model else [])]))
            return url, gr.update(value=key, visible=not is_local_ollama(url)), origin(url), gr.update(open=profile == "自定义地址"), "", "", self._key_link(provider, url), gr.update(choices=choices,value=model), embed, picker, message if "未能" in message or "无法" in message else ""
        self.profile.input(change_profile, [self.provider,self.profile,self.base_url,self.api_key,self.chat_model,self.embed_model], [self.base_url,self.api_key,self.endpoint_origin,self.address_options,self.result,self.model_status,self.key_link,self.chat_model,self.embed_model,self.saved_connection,self.remember_status], show_progress="hidden")
        def change_endpoint(url, previous, key):
            key = key if tuple(previous) == origin(url) else ""
            return gr.update(value=key, visible=not is_local_ollama(url)), origin(url), "", ""
        self.base_url.input(change_endpoint, [self.base_url,self.endpoint_origin,self.api_key], [self.api_key,self.endpoint_origin,self.result,self.model_status], show_progress="hidden")
        self.fetch_btn.click(_fetch_models, [self.base_url,self.api_key,self.chat_model], [self.chat_model,self.model_status])
        self.test_btn.click(lambda key, url, model: _test_llm(url,key,model or "")[0], [self.api_key,self.base_url,self.chat_model], [self.result])
        remember_inputs = [self.draft_provider,self.api_key,self.base_url,self.chat_model,self.embed_model]
        remember_outputs = [self.saved_connection,self.remember_status]
        self.remember_btn.click(self._remember, remember_inputs, remember_outputs, show_progress="hidden")
        self.api_key.blur(self._remember, remember_inputs, remember_outputs, show_progress="hidden")
        self.chat_model.input(self._remember, remember_inputs, remember_outputs, show_progress="hidden")
        self.save_btn.click(self._save, [self.api_key,self.base_url,self.chat_model,self.embed_model,self.provider], [self.result,self.status_display,self.saved]).then(
            self._remember, remember_inputs, remember_outputs, show_progress="hidden",
        )

    def as_gradio_component(self):
        return None
