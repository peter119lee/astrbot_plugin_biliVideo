# AstrBot 插件后台主动唤醒对话文档

## 概述

本文档记录如何在 AstrBot 插件中实现后台任务完成后主动唤醒主对话的功能。

## 核心流程

```
用户发起请求 → 插件 Tool 处理 → 启动后台任务 → 后台任务完成 → 创建 CronMessageEvent → 调用 build_main_agent → 主对话 AI 被唤醒并发送消息
```

## 关键组件

### 1. CronMessageEvent

`CronMessageEvent` 是一个合成的消息事件，用于触发主 agent 循环。

```python
from astrbot.core.cron.events import CronMessageEvent

cron_event = CronMessageEvent(
    context=plugin_context,           # 插件上下文 (Context)
    session=event.session,            # 原始事件的 session (MessageSession)
    message="你的消息内容",             # 发送给 AI 的消息
    sender_id="your_plugin_id",       # 发送者 ID（可选）
    sender_name="插件名称",             # 发送者名称（可选）
)
```

**重要属性：**
- `session`: 必须传递原始事件的 session，确保消息发送到正确的会话
- `unified_msg_origin (umo)`: 会话标识，从 `cron_event.unified_msg_origin` 获取
- `platform_meta.name`: 默认为 "cron"

### 2. build_main_agent

`build_main_agent` 用于构建主对话代理。

```python
from astrbot.core.astr_main_agent import (
    MainAgentBuildConfig,
    _get_session_conv,
    build_main_agent,
)
```

### 3. MainAgentBuildConfig

主对话构建配置：

```python
config = MainAgentBuildConfig(
    tool_call_timeout=120,            # 工具调用超时时间
    llm_safety_mode=False,            # LLM 安全模式
    streaming_response=False,         # 是否流式响应
    computer_use_runtime="local",     # 可选: "none" / "local" / "sandbox"
)
```

**`computer_use_runtime` 说明：**
- `"none"`: 不添加额外工具
- `"local"`: 添加 shell 和 python 执行工具（默认）
- `"sandbox"`: 添加沙箱环境工具

### 4. ProviderRequest

请求对象，包含对话历史和提示词：

```python
from astrbot.core.provider.entities import ProviderRequest

req = ProviderRequest()
req.conversation = conv               # 对话历史对象
req.prompt = "你的提示词"              # 用户消息
req.func_tool = ToolSet()             # 工具集
```

### 5. SEND_MESSAGE_TO_USER_TOOL

发送消息给用户的工具：

```python
from astrbot.core.astr_main_agent_resources import (
    SEND_MESSAGE_TO_USER_TOOL,
)

req.func_tool.add_tool(SEND_MESSAGE_TO_USER_TOOL)
```

## 完整示例代码

```python
async def _background_process(
    self,
    keyword: str,
    event: AstrMessageEvent,
):
    """后台处理任务，完成后直接唤醒主对话"""
    try:
        # 导入所需模块
        from astrbot.core.cron.events import CronMessageEvent
        from astrbot.core.astr_main_agent import (
            MainAgentBuildConfig,
            _get_session_conv,
            build_main_agent,
        )
        from astrbot.core.astr_main_agent_resources import (
            SEND_MESSAGE_TO_USER_TOOL,
        )
        from astrbot.core.provider.entities import ProviderRequest
        from astrbot.core.agent.tool import ToolSet

        # ... 执行后台任务 ...

        # 构建提示词
        prompt = (
            f"后台任务已完成。\n\n"
            f"处理结果: 成功 xxx 个\n"
            f"请使用 send_message_to_user 工具发送消息告诉用户任务完成情况。"
        )

        # 创建 CronMessageEvent
        cron_event = CronMessageEvent(
            context=self.plugin_instance.context,
            session=event.session,
            message=prompt,
            sender_id="your_plugin",
            sender_name="插件名称",
        )

        # 获取配置
        umo = cron_event.unified_msg_origin
        cfg = self.plugin_instance.context.get_config(umo=umo)
        tool_call_timeout = cfg.get("provider_settings", {}).get("tool_call_timeout", 120)

        # 构建配置
        config = MainAgentBuildConfig(
            tool_call_timeout=tool_call_timeout,
            llm_safety_mode=False,
            streaming_response=False,
        )

        # 构建请求
        req = ProviderRequest()
        conv = await _get_session_conv(event=cron_event, plugin_context=self.plugin_instance.context)
        req.conversation = conv

        # 加载对话历史
        import json
        context_history = json.loads(conv.history) if conv.history else []
        if context_history:
            req.contexts = context_history
            context_dump = req._print_friendly_context()
            req.contexts = []
            req.system_prompt += (
                "\n\nBelow is your previous conversation history:\n"
                f"---\n{context_dump}\n---\n"
            )

        # 设置提示词和工具
        req.prompt = prompt
        if not req.func_tool:
            req.func_tool = ToolSet()
        req.func_tool.add_tool(SEND_MESSAGE_TO_USER_TOOL)

        # 构建主对话 agent
        agent_result = await build_main_agent(
            event=cron_event,
            plugin_context=self.plugin_instance.context,
            config=config,
            req=req,
        )

        if not agent_result:
            logger.error("无法构建主对话 agent")
            return

        # 运行 agent 直到完成
        runner = agent_result.agent_runner
        async for _ in runner.step_until_done(30):
            pass

        logger.info("主对话处理完成")

    except Exception as e:
        logger.error(f"后台处理失败: {e}", exc_info=True)
```

## 注意事项

### 1. 导入位置

所有 `astrbot.core.*` 的导入建议放在方法内部，避免插件加载时出现导入错误。

### 2. Session 传递

必须正确传递原始事件的 `session`，否则消息无法发送到正确的会话。

### 3. 对话历史

使用 `_get_session_conv` 获取对话历史，并通过 `req.contexts` 传递给 AI，确保 AI 能看到之前的对话。

### 4. 工具限制

- `SEND_MESSAGE_TO_USER_TOOL` 是必须的，否则 AI 无法发送消息
- 如果 `computer_use_runtime="local"`，AI 还可以使用 shell 和 python 工具
- 如果不需要这些工具，设置 `computer_use_runtime="none"`

### 5. Prompt 编写

prompt 中应明确告诉 AI：
- 使用 `send_message_to_user` 工具发送消息
- 任务完成情况
- 需要告知用户的关键信息

### 6. 超时处理

`runner.step_until_done(max_steps)` 中的 `max_steps` 控制 AI 最多执行多少轮工具调用，避免无限循环。

## 工具调用流程图

```
CronMessageEvent 创建
        ↓
获取对话历史 (_get_session_conv)
        ↓
构建 ProviderRequest
        ↓
添加工具 (SEND_MESSAGE_TO_USER_TOOL)
        ↓
build_main_agent 构建 agent
        ↓
runner.step_until_done() 执行
        ↓
AI 调用工具 (如 send_message_to_user)
        ↓
消息发送到用户
```

## 与定时任务 (FutureTask) 的区别

| 方案 | 优点 | 缺点 |
|------|------|------|
| CronMessageEvent + build_main_agent | 直接、即时、不需要等待 | 代码稍复杂 |
| create_future_task | 简单、可设置延迟 | 需要等待，时间可能已过期 |

**推荐使用 CronMessageEvent 方案**，因为后台任务完成时通常需要立即响应。

## 常见问题

### Q: 消息没有发送到用户？

检查：
1. `event.session` 是否正确传递
2. `SEND_MESSAGE_TO_USER_TOOL` 是否已添加
3. prompt 是否明确要求 AI 发送消息

### Q: AI 看不到之前的对话？

确保：
1. 使用 `_get_session_conv` 获取对话
2. 正确设置 `req.contexts`
3. 在 `req.system_prompt` 中附加历史

### Q: 导入失败？

将导入放在方法内部：
```python
async def my_method(self):
    from astrbot.core.cron.events import CronMessageEvent
    # ...
```

## 相关文件

- `astrbot/core/cron/events.py` - CronMessageEvent 定义
- `astrbot/core/astr_main_agent.py` - build_main_agent 定义
- `astrbot/core/astr_main_agent_resources.py` - SEND_MESSAGE_TO_USER_TOOL 定义
- `astrbot/core/provider/entities.py` - ProviderRequest 定义

## 版本信息

- AstrBot 版本: v4.22.3+
- 文档更新日期: 2026-04-10
