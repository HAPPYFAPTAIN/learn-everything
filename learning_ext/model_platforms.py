from urllib.parse import urlsplit
from pathlib import Path
import hashlib
import hmac
import json
import secrets


PLATFORMS = {
    "deepseek": {"name": "DeepSeek", "mark": "D", "tag": "官方 API", "profiles": {"官方接口": "https://api.deepseek.com/v1"}, "models": ["deepseek-flash", "deepseek-v4-pro"], "key_url": "https://platform.deepseek.com/api_keys", "docs": "https://api-docs.deepseek.com/", "note": "使用 DeepSeek 开放平台的 API 密钥。"},
    "qwen": {"name": "阿里云百炼", "mark": "Q", "tag": "Qwen · 千问", "profiles": {"中国内地 · 北京": "https://dashscope.aliyuncs.com/compatible-mode/v1", "国际 · 新加坡": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"}, "models": ["qwen-plus", "qwen-flash"], "key_url": "https://bailian.console.aliyun.com/", "docs": "https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope", "note": "密钥须与地区一致。业务空间专属域名可在连接地址中填写。"},
    "bigmodel": {"name": "智谱 BigModel", "mark": "GLM", "tag": "GLM · 开放平台", "profiles": {"通用 API": "https://open.bigmodel.cn/api/paas/v4"}, "models": ["glm-5.3"], "key_url": "https://bigmodel.cn/console/usercenter/apikeys", "docs": "https://docs.bigmodel.cn/cn/guide/develop/http/introduction", "note": "默认使用通用 API。已有的 Coding 专属地址会保留，请按套餐适用范围使用。"},
    "openai": {"name": "OpenAI", "mark": "O", "tag": "官方 API", "profiles": {"官方接口": "https://api.openai.com/v1"}, "models": [], "key_url": "https://platform.openai.com/api-keys", "docs": "https://developers.openai.com/api/reference/resources/models/methods/list", "note": "使用 API 平台密钥；ChatGPT 订阅与 API 额度分开。选择支持 Chat Completions 的模型。"},
    "gemini": {"name": "Google Gemini", "mark": "✦", "tag": "Google AI Studio", "profiles": {"OpenAI 兼容接口": "https://generativelanguage.googleapis.com/v1beta/openai"}, "models": [], "key_url": "https://aistudio.google.com/apikey", "docs": "https://ai.google.dev/gemini-api/docs/openai", "note": "使用 Google AI Studio 的 API 密钥。"},
    "siliconflow": {"name": "硅基流动", "mark": "S", "tag": "SiliconFlow", "profiles": {"中国站": "https://api.siliconflow.cn/v1"}, "models": [], "key_url": "https://cloud.siliconflow.cn/", "docs": "https://docs.siliconflow.cn/docs/api/chat-completions-post", "note": "读取模型列表后选择，也可以填写完整模型 ID。"},
    "openrouter": {"name": "OpenRouter", "mark": "↗", "tag": "多模型平台", "profiles": {"官方接口": "https://openrouter.ai/api/v1"}, "models": [], "key_url": "https://openrouter.ai/settings/keys", "docs": "https://openrouter.ai/docs/quickstart", "note": "模型 ID 使用平台提供的完整名称。"},
    "ollama": {"name": "Ollama", "mark": "L", "tag": "本机模型", "profiles": {"本机服务": "http://localhost:11434/v1"}, "models": [], "key_url": "", "docs": "https://docs.ollama.com/api/openai-compatibility", "note": "先启动 Ollama，再读取本机已安装的模型。"},
    "custom": {"name": "自定义连接", "mark": "+", "tag": "OpenAI 兼容", "profiles": {"自定义地址": ""}, "models": [], "key_url": "", "docs": "", "note": "适用于支持 /chat/completions 的网关或本地服务。"},
}

PLATFORMS.update({
    "minimax": {"name":"MiniMax", "mark":"M", "tag":"海螺 · 开放平台", "group":"国内平台", "profiles":{"中国站":"https://api.minimax.cn/v1", "国际站":"https://api.minimax.io/v1"}, "models":["MiniMax-M3.1-Flash","MiniMax-M3"], "key_url":"https://platform.minimax.cn/", "docs":"https://platform.minimax.cn/docs/api-reference/text-openai-api", "note":"中国站和国际站使用对应账户的密钥。"},
    "kimi": {"name":"Kimi · 月之暗面", "mark":"K", "tag":"Moonshot AI", "group":"国内平台", "profiles":{"中国站":"https://api.moonshot.cn/v1", "国际站":"https://api.moonshot.ai/v1"}, "models":["kimi-k3.1-pro","kimi-k3","kimi-k2.6"], "key_url":"https://platform.kimi.com/", "docs":"https://platform.kimi.com/docs/guide/migrating-from-openai-to-kimi", "note":"使用 Kimi API 开放平台密钥，选择与账户对应的站点。"},
    "volcengine": {"name":"火山方舟", "mark":"火", "tag":"豆包 · Volcengine", "group":"国内平台", "profiles":{"北京 · 通用 API":"https://ark.cn-beijing.volces.com/api/v3"}, "models":[], "key_url":"https://ark.volcengine.com/region:cn-beijing/apikey", "docs":"https://www.volcengine.com/docs/82379/1330310", "note":"填写已开通的模型 ID 或推理接入点 ID。"},
    "groq": {"name":"Groq", "mark":"G", "tag":"高速推理", "group":"海外平台", "profiles":{"官方接口":"https://api.groq.com/openai/v1"}, "models":[], "key_url":"https://console.groq.com/keys", "docs":"https://console.groq.com/docs/openai", "note":"读取当前账户可用的模型列表。"},
    "together": {"name":"Together AI", "mark":"T", "tag":"开源模型推理", "group":"海外平台", "profiles":{"官方接口":"https://api.together.ai/v1"}, "models":[], "key_url":"https://api.together.ai/", "docs":"https://docs.together.ai/docs/inference/openai-compatibility", "note":"使用平台提供的完整模型 ID。"},
    "mistral": {"name":"Mistral AI", "mark":"M", "tag":"Mistral Studio", "group":"海外平台", "profiles":{"官方接口":"https://api.mistral.ai/v1"}, "models":[], "key_url":"https://console.mistral.ai/", "docs":"https://docs.mistral.ai/api/endpoint/chat", "note":"使用 Mistral Studio 的 API 密钥。"},
    "xai": {"name":"xAI · Grok", "mark":"X", "tag":"Grok API", "group":"海外平台", "profiles":{"官方接口":"https://api.x.ai/v1"}, "models":[], "key_url":"https://console.x.ai/", "docs":"https://docs.x.ai/developers/model-capabilities/text/generate-text", "note":"选择支持 Chat Completions 的对话模型。"},
    "opencode": {"name":"OpenCode", "mark":"OC", "tag":"Zen · Go · Go Plus", "group":"聚合中转", "profiles":{"Go / Go Plus · 订阅":"https://opencode.ai/inference/go/openai/v1", "Console / Zen · 按量":"https://opencode.ai/inference/openai/v1"}, "models":["glm-5.3-flash","kimi-k3.1-pro","deepseek-v4.1-flash"], "key_url":"https://opencode.ai/console", "docs":"https://opencode.ai/v2/docs/console/go/", "note":"Go 与 Go Plus 共用订阅接口，额度由账户决定。适用于编程学习；当前接入兼容对话模型。"},
})
PLATFORMS.update(json.loads(Path(__file__).with_name("model_platform_catalog.json").read_text(encoding="utf-8")))
PLATFORMS["custom"].update(name="自定义 / 中转站", tag="任意兼容平台", group="聚合中转", note="填写中转站的 API 根地址、密钥和模型 ID。支持 New API、One API 等兼容网关。")
for key, cfg in PLATFORMS.items():
    cfg.setdefault("group", "国内平台" if key in {"deepseek","qwen","bigmodel","siliconflow"} else "本地服务" if key == "ollama" else "聚合中转" if key == "openrouter" else "海外平台")
_ORDER = ["deepseek","qwen","bigmodel","minimax","kimi","volcengine","siliconflow","opencode","openrouter","openai","gemini"]
PLATFORMS = {key:PLATFORMS[key] for key in [*_ORDER, *(key for key in PLATFORMS if key not in _ORDER and key not in {"ollama","custom"}), "ollama", "custom"]}
_SESSION_SALT = secrets.token_bytes(32)


def platform_filter_html():
    from html import escape
    data = {key:{"name":cfg["name"], "tag":cfg["tag"], "group":cfg["group"], "icon":platform_icon_url(key)} for key,cfg in PLATFORMS.items()}
    categories = ["全部","国内平台","海外平台","聚合中转","本地服务"]
    buttons = ''.join(f'<button type="button" data-group="{name}" aria-pressed="{str(name == "全部").lower()}">{name}</button>' for name in categories)
    return f'<div id="le-platform-filter" data-catalog="{escape(json.dumps(data,ensure_ascii=False),quote=True)}"><input type="search" aria-label="搜索模型平台" placeholder="搜索平台，如 Kimi、Go…"><div class="le-platform-categories">{buttons}</div><span class="le-platform-count" role="status">{len(data)} 个平台</span></div>'


def platform_css():
    return '\n'.join(f'#le-platform-picker label:has(input[value="{key}"]) {{ --platform-icon: url("{platform_icon_url(key)}"); --platform-tag: {json.dumps(cfg["tag"],ensure_ascii=False)}; }}' for key,cfg in PLATFORMS.items())


def platform_icon_url(provider):
    from urllib.parse import quote
    key = provider if provider in PLATFORMS else "custom"
    path = Path(__file__).resolve().parent / "assets" / "vendor" / "platform-icons" / f"{key}.svg"
    return "/file=" + quote(path.as_posix(), safe="/:")


def is_opencode_go(url):
    return origin(url)[1] == "opencode.ai" and urlsplit(url).path.startswith(("/inference/go/", "/zen/go/", "/go/"))


def models_url(base_url):
    if origin(base_url)[1] == "opencode.ai":
        return "https://opencode.ai/inference/go/v1/models" if is_opencode_go(base_url) else "https://opencode.ai/inference/v1/models"
    return base_url.strip().rstrip('/') + '/models'


def compatible_model(base_url, model):
    if origin(base_url)[1] != "opencode.ai":
        return True
    name = model.lower()
    if name.startswith(("gpt-", "grok-", "claude-", "gemini-", "muse-", "jev-")):
        return False
    if is_opencode_go(base_url):
        return not name.startswith("qwen") and name not in {"minimax-m3", "minimax-m2.7"}
    return name not in {"qwen3.8-flash", "qwen3.6-plus", "qwen3.5-plus"} and not name.endswith('-free') and name != 'big-pickle'


def adapt_chat_params(base_url, params):
    result = dict(params)
    model = str(result.get('model', '')).lower().split('/')[-1]
    if model.startswith('kimi-'):
        result.pop('temperature', None)
        result.pop('top_p', None)
    if model.startswith(('kimi-k3.1', 'minimax-m3.1')):
        result.setdefault('reasoning_effort', 'low')
    if origin(base_url or '')[1] == 'opencode.ai':
        if not compatible_model(base_url, model):
            raise ValueError('这个 OpenCode 模型使用其他接口协议，请从兼容对话模型列表中选择。')
        headers = dict(result.get('extra_headers') or {})
        headers['User-Agent'] = 'LearnEverything/1.0'
        if is_opencode_go(base_url):
            first = next((m for m in result.get('messages', []) if m.get('role') == 'user'), {})
            digest = hmac.new(_SESSION_SALT, json.dumps(first,ensure_ascii=False,sort_keys=True).encode(), hashlib.sha256).hexdigest()
            headers['x-opencode-session'] = digest
        result['extra_headers'] = headers
    return result


def origin(url):
    try:
        parsed = urlsplit(url.strip())
        return (parsed.scheme, parsed.hostname, parsed.port)
    except ValueError:
        return (None, None, None)


def detect_platform(url):
    host = origin(url)[1]
    for key, cfg in PLATFORMS.items():
        if key == "ollama":
            if is_local_ollama(url):
                return key
            continue
        if host and any(host == origin(base)[1] for base in cfg["profiles"].values()):
            return key
    if host and (host.endswith(".maas.aliyuncs.com")):
        return "qwen"
    if host == "127.0.0.1" and origin(url)[2] == 11434:
        return "ollama"
    return "custom"


def profile_for(platform, url):
    return next((name for name, base in PLATFORMS[platform]["profiles"].items() if base.rstrip("/") == url.rstrip("/")), "自定义地址")


def platform_draft(platform, saved):
    if detect_platform(saved.get("base_url", "")) == platform:
        return dict(saved)
    cfg = PLATFORMS[platform]
    return {"base_url": next(iter(cfg["profiles"].values())), "api_key": "", "chat_model": next(iter(cfg["models"]), ""), "embed_model": ""}


def connection_error(base_url, api_key, model=None):
    try:
        parsed = urlsplit(base_url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return "请填写完整的接口地址，不要包含密钥、查询参数或账号密码。"
        parsed.port
    except ValueError:
        return "接口地址格式不正确。"
    if any(c in base_url + api_key + (model or "") for c in "\r\n"):
        return "连接信息不能包含换行，请重新粘贴。"
    if not api_key.strip() and not is_local_ollama(base_url):
        return "请先填写 API Key。"
    if model is not None and not model.strip():
        return "请先选择或填写对话模型名称。"
    if model and not compatible_model(base_url, model):
        return "这个 OpenCode 模型使用其他接口协议或仅限官方客户端，请选择列表中的兼容对话模型。"
    return ""


def is_local_ollama(url):
    return origin(url)[1] in {"localhost", "127.0.0.1", "::1"} and origin(url)[2] == 11434


def request_key(url, key):
    return key.strip() or ("ollama" if is_local_ollama(url) else "")


def model_ids(payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid model list")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Invalid model list")
    excluded = ("embedding", "rerank", "whisper", "tts", "image", "dall-e", "moderation", "transcri", "realtime", "audio", "sora")
    return sorted({item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip() and not any(word in item["id"].lower() for word in excluded)})
