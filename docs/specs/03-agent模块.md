# 03 · 简单 Agent 模块（provider 预设 + 统一调用）

> 状态：规划中 · 模块：`scripts/agent.py`（新增）· 依赖：`common.py` 配置层
> 对应 `00-规划总览.md` 主线需求 2

## Problem Statement

用户需要"简单 agent"：输入一段提示词，调用模型 API 生成剧本 / 分镜 / 资产清单等内容。
模型服务可能是远端（DeepSeek / Qwen / Kimi）也可能是本地（Ollama 或任意 OpenAI 兼容服务），
用户只希望通过 **config.yaml 切换配置**，不修改代码。
现有 `ai_writer.py` 的 LLM 层（`_llm` / `call_llm`）写死了单一 base/model/key，无法满足多提供商。

## Solution

新增 `scripts/agent.py`：从 config.yaml 解析 provider 预设，输出统一的
`chat(messages)` / `generate(task, payload)` 接口（OpenAI 兼容协议，仅标准库）。
`ai_writer.py` 的 LLM 层迁移为调用该模块（保持旧配置键兼容）。

### 配置契约（config.yaml `llm:` 段，向后兼容）

```yaml
llm:
  provider: deepseek            # 当前生效提供商：deepseek | qwen | kimi | local | custom
  providers:                    # 预设表；base 可带 /v1 也可不带（统一规范化）
    deepseek:
      base: https://api.deepseek.com
      model: deepseek-chat
      api_key: ""
    qwen:
      base: https://dashscope.aliyuncs.com/compatible-mode/v1
      model: qwen-plus
      api_key: ""
    kimi:
      base: https://api.moonshot.cn/v1
      model: kimi-k2-0711-preview
      api_key: ""
    local:                      # Ollama 等本地 OpenAI 兼容服务
      base: http://127.0.0.1:11434/v1
      model: qwen2.5:7b
      api_key: ""
  timeout: 600
  # 兼容旧键：llm.base / llm.model / llm.api_key（作为 custom provider 兜底）
```

### 模块接口

- `resolve_provider(cfg) -> {provider, base, model, api_key}`：按 `provider` 键取预设；
  缺失时报错并列出可用提供商；旧键 `llm.base/model/api_key` 作为 `custom` 兜底。
- `chat_endpoint(base) -> str`：规范化 URL——`base` 以 `/v1` 结尾则原样，否则补 `/v1`；再拼 `/chat/completions`。
- `chat(base, model, key, messages, temperature, max_tokens, timeout) -> str`：POST 一次对话，返回正文文本。
- `generate(task, **payload) -> str`：读配置 → 选提供商 → 用 `prompts/` 模板拼 messages → `chat`。
  首批 task：`storyboard_from_script`（剧本→分镜提示词）、`shot_ref`（分镜→参考图提示词，M1 使用）。
- `parse_chat_response(data) -> str`：正文优先 `choices[0].message.content`，空则回退 `reasoning_content`；
  错误响应抛 `AgentError`（含 HTTP 状态与上游错误消息）。

## User Stories

1. 作为创作者，我想在 config.yaml 里把 `provider` 改成 `qwen` 并填上 key，就能让 agent 换用 Qwen 生成剧本，以便按成本/效果灵活选模型。
2. 作为创作者，我想把 provider 指到本地 Ollama（`local` 预设），以便断网或数据敏感时在本机生成。
3. 作为创作者，我想在配置缺失/提供商名写错时看到明确的错误信息（列出可用预设），以便快速修正配置。
4. 作为创作者，我想让 agent 一次性产出"剧本→分镜"两段内容，以便减少手工步骤（沿用现有四层链式编剧）。
5. 作为开发者，我想直接调用 `agent.chat()` 传入 messages，以便未来 harness agent / skill 复用同一接口。
6. 作为开发者，我想让旧的 `llm.base/model/api_key` 配置继续可用，以便平滑升级不停机。

## Implementation Decisions

- 仅标准库（`urllib.request` + `json`），不引入 requests/openai SDK——项目约束"零第三方依赖"。
- 模块名 `agent.py`（不叫 llm.py）：概念上它是"生成 agent"的最小内核，未来 skill/harness 都挂它。
- 规范化规则：`base` 不带 `/v1` 时补 `/v1`；`local` 预设默认 Ollama 的 OpenAI 兼容端口 11434。
- 错误类型：`AgentError(provider, status, upstream_msg)`；配置错 → `ConfigError`（`common.py` 统一）。
- `generate()` 的提示词模板放 `prompts/agent/`（与现有 `prompts/` 目录共存），模板是纯文本函数，便于测试。

## Testing Decisions（seams）

只测以下公共 seam（详见 `05-测试策略.md`）：

1. `resolve_provider` — 预设选择、缺 key 报错、旧键兜底、未知 provider 报错；
2. `chat_endpoint` — `/v1` 规范化（带/不带/尾部斜杠）；
3. `parse_chat_response` — content / reasoning_content 回退、错误响应抛 AgentError；
4. `generate` 的模板拼接 — 用 mock 的 `chat`（`unittest.mock`），断言 messages 内容与返回透传；
5. HTTP 层用 `unittest.mock.patch('urllib.request.urlopen')` 返回假响应——不打真实网络。

反模式提醒：不断言内部 urllib 细节（如 Request 对象字段），只测公开行为。

## Out of Scope

- 流式输出 / 多轮对话记忆 / function calling（未来版本）；
- 模型计费、用量统计、重试与限流策略（未来版本）；
- 图片/视频模型的 API 直调（走 ComfyUI，不走 LLM API）。

## Further Notes

- `config.yaml` 现有 key 已含真实 api_key，后续预设填充前先确认是否应移入环境变量/独立 secret 文件（M3 处理）。
- `ai_writer.call_llm` 迁移后保留薄兼容层，避免一次性重写全部调用点。
