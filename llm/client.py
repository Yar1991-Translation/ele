"""OpenAI 兼容的 LLM 客户端。

火山方舟（豆包）、DeepSeek、Kimi、智谱、OpenAI 等均走同一套协议，
只需在 .env 里改 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL。

多提供商：config.yaml 的 providers 段可配置其他提供商，
模型引用用「提供商名/模型名」语法（见 resolve_ref）。
"""
import json
import os
import re
import time

from dotenv import load_dotenv

load_dotenv()

# 每次程序运行内的累计用量（模块级，方便各阶段统一打印）
usage_stats = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


class LLMError(Exception):
    pass


def _is_param_reject(err):
    """判断异常是否为"服务端不认识该参数"（如思考强度参数用于不支持思考的模型）。"""
    text = str(err).lower()
    return any(k in text for k in ("unknown", "not support", "invalid parameter",
                                   "unexpected", "extra_forbidden", "unrecognized",
                                   "does not support", "400")) or type(err).__name__ in (
        "BadRequestError", "UnprocessableEntityError", "TypeError")


class LLMClient:
    def __init__(self, base_url=None, api_key=None, model=None, timeout=None):
        from openai import OpenAI

        self.base_url = base_url or os.getenv("LLM_BASE_URL", "")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("LLM_MODEL", "")
        # 展示用标签（分模型用量统计的 key），llm_for 解析出提供商时会改写
        self.label = self.model
        # 单次请求超时：默认 180s（写作长文够用），可用 LLM_TIMEOUT 环境变量调整。
        # 分类/提炼这类短调用会在 chat() 里按次传更短的 timeout。
        self.timeout = timeout or int(os.getenv("LLM_TIMEOUT", "180"))
        if not (self.base_url and self.api_key and self.model):
            raise LLMError(
                "LLM 配置不完整，请检查 .env 中的 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL"
                "（可参考 .env.example）"
            )
        # SDK 自带网络层重试，这里再关小一点，内容层重试自己控制
        self.client = OpenAI(
            base_url=self.base_url, api_key=self.api_key,
            timeout=self.timeout, max_retries=2,
        )

    def chat(self, system, user, temperature=0.7, retries=4, sleep_base=5.0,
             timeout=None, extra_body=None):
        """带重试的单轮对话（chat_messages 的 system+user 便捷形式）。"""
        return self.chat_messages(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            temperature=temperature, retries=retries, sleep_base=sleep_base,
            timeout=timeout, extra_body=extra_body)

    def chat_messages(self, messages, temperature=0.7, retries=4, sleep_base=5.0,
                      timeout=None, extra_body=None):
        """带重试的多轮对话。messages 为 OpenAI 格式消息列表。

        timeout：本次调用的单次请求超时秒数（不传用客户端默认）。
        extra_body：直接并入请求体的厂商扩展参数，如思考强度
          {"thinking": {"type": "enabled"}}；若服务端不支持会自动去掉重试。
        """
        last_err = None
        used_extra = extra_body
        for attempt in range(retries):
            try:
                kwargs = {"temperature": temperature}
                if timeout:
                    kwargs["timeout"] = timeout
                if used_extra:
                    kwargs["extra_body"] = used_extra
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    **kwargs,
                )
                content = resp.choices[0].message.content if resp.choices else None
                if not content or not content.strip():
                    raise LLMError("模型返回了空内容")
                usage = getattr(resp, "usage", None)
                if usage:
                    label = self.label or self.model
                    usage_stats["calls"] += 1
                    usage_stats["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
                    usage_stats["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
                    by = usage_stats.setdefault("by_model", {}).setdefault(
                        label, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
                    by["calls"] += 1
                    by["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
                    by["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
                return content
            except Exception as e:  # noqa: BLE001 网络/限流/超时都值得再试
                # 思考强度等扩展参数不被当前模型/服务支持时，去掉参数回退重试
                if used_extra and _is_param_reject(e):
                    print(f"    思考强度参数不被支持（{str(e)[:80]}），已回退为普通调用")
                    used_extra = None
                    continue
                last_err = e
                wait = sleep_base * (2 ** attempt)
                print(f"    LLM 调用失败（第{attempt + 1}/{retries}次）：{type(e).__name__}: "
                      f"{str(e)[:160]}，{wait:.0f}s 后重试")
                time.sleep(wait)
        raise LLMError(f"LLM 调用重试 {retries} 次后仍失败：{last_err}")

    def chat_json(self, system, user, temperature=0.5, retries=4, timeout=None,
                  extra_body=None):
        """要求模型返回 JSON 并解析；解析失败会把错误反馈给模型重试一次。"""
        text = self.chat(system, user, temperature=temperature, retries=retries,
                         timeout=timeout, extra_body=extra_body)
        try:
            return extract_json(text)
        except (ValueError, json.JSONDecodeError):
            # 给模型一次自我修正的机会
            fix_prompt = (
                "你上一次的输出无法被解析为 JSON。请严格只输出一个合法的 JSON 对象，"
                "不要输出任何解释、markdown 代码块标记或其他文字。\n\n你上一次的输出：\n" + text[:4000]
            )
            text2 = self.chat(system, fix_prompt, temperature=0.2, retries=1,
                              timeout=timeout)
            return extract_json(text2)


def providers_map(providers):
    """providers 段归一化为 {名字: {base_url, api_key, ...}}。

    兼容两种形态：dict（手写 config.yaml）与 list of dict（GUI 编辑器存储，
    每项含 name/base_url/api_key）。
    """
    if isinstance(providers, dict):
        return providers
    if isinstance(providers, list):
        out = {}
        for p in providers:
            if isinstance(p, dict) and (p.get("name") or "").strip():
                out[p["name"].strip()] = p
        return out
    return {}


def resolve_ref(ref, providers=None):
    """解析模型引用 -> (base_url, api_key, model, provider_name)。

    - 纯模型名（如 mimo-v2.6-pro）：走 .env 默认提供商（base_url/api_key 返回 None）；
    - 「提供商名/模型名」（如 deepseek/deepseek-chat）：providers 为
      config.yaml 的 providers 段（dict 或 list，见 providers_map），
      按第一个 / 切分查表；前缀不是已知提供商时整串按默认提供商的模型名
      处理（打印警告）。
    """
    ref = (ref or "").strip()
    pmap = providers_map(providers)
    if "/" in ref:
        pname, model = ref.split("/", 1)
        pname = pname.strip()
        p = pmap.get(pname)
        if isinstance(p, dict) and (p.get("base_url") or "").strip():
            return ((p.get("base_url") or "").strip(), (p.get("api_key") or "").strip(),
                    model.strip(), pname)
        print("⚠ 模型引用「{}」的提供商「{}」不在 providers 配置里，按默认提供商的模型名处理"
              .format(ref, pname))
    return (None, None, ref, None)


def llm_for(model, base=None, providers=None):
    """按阶段模型配置取客户端：留空或与主客户端同款则复用 base，否则派生。

    model 支持「提供商/模型」语法（见 resolve_ref），providers 为
    config.yaml 的 providers 段。判同款的标准：默认提供商且模型名相同。
    """
    base = base or LLMClient()
    m = (model or "").strip()
    if not m:
        return base
    base_url, api_key, model_name, pname = resolve_ref(m, providers)
    if not base_url and model_name == base.model:
        return base
    client = LLMClient(base_url=base_url, api_key=api_key, model=model_name)
    client.label = "{}/{}".format(pname, model_name) if pname else model_name
    return client


def extract_json(text):
    """从模型输出中提取 JSON（容忍 markdown 代码块、前后废话）。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 找第一个 { 或 [ 到最后一个配对的 } 或 ]
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
    raise ValueError("输出中找不到 JSON：" + text[:200])
