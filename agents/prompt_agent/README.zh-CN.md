# Prompt 智能体

[English](README.md) | **简体中文**

`PromptAgent` 和 `StreamingPromptAgent` 根据截图与任务指令生成 Python 代码或 `computer_13` JSON 动作，共用桌面环境和任务评价器。

## 使用方式

在项目根目录执行，凭据配置在本地 `.env`：

```powershell
python -m pip install -e ".[responses]"
python run.py --agent prompt --task task001 --check
python run.py --agent prompt --task task001
python run.py --agent prompt-stream --action-space computer_13 --task task001
```

| 参数 | 默认值 | 用途 |
| --- | --- | --- |
| `--action-space` | `pydirectinput` | Python 代码，或 `computer_13` JSON |
| `--max-trajectory-length` | `3` | 最近的截图 / 回复对数；`0` 仅发送当前截图 |
| `--wait-seconds` | `1.0` | WAIT 等待时长 |
| `--request-timeout` | `120` | 每次网络尝试的超时秒数 |
| `--max-tokens` | 不指定 | 输出 token 上限；OpenAI 使用 API 默认值，Anthropic 默认为 4096 |
| `--reasoning-effort` | `medium` | 供应商对应的推理强度；空字符串省略该配置 |

每轮都会发送任务指令。默认模型为 `gpt-6.1-sol`，请根据实际接口选择可用模型。准备与执行时限见[项目说明](../../README.zh-CN.md)。

## 供应商与凭据

模型名以 `claude-` 开头时选择 `providers/anthropic.py`，其余名称选择 `providers/openai.py`。`agent.py` 负责历史、动作解析和执行的公共流程。

| 供应商 | 安装依赖组 | 凭据 | 地址优先级 |
| --- | --- | --- | --- |
| OpenAI Responses | `.[responses]` | `OPENAI_API_KEY` 或 `OPENAI_OAUTH_CREDENTIALS` | `--base-url`、`OPENAI_BASE_URL`、SDK 默认地址 |
| Anthropic Messages | `.[anthropic]` | `ANTHROPIC_AUTH_TOKEN`，其次 `CLAUDE_CODE_OAUTH_TOKEN` | `--base-url`、`ANTHROPIC_BASE_URL`、供应商默认地址 |

OpenAI Prompt 模式发送文本和图片，不使用 computer 工具调用；接口需要支持图片输入与文本输出。OAuth 文件刷新规则见 [Responses 凭据说明](../openai_responses/README.zh-CN.md)。

Anthropic 适配器使用 SDK Messages、OAuth auth token、系统消息中的 billing header 和 beta 查询选项。这是适配器的实验协议，需要核对账户和接口兼容性。它不使用 OpenAI 凭据刷新模块；Anthropic token 失效后应在本地更新并重启进程。effort 支持 `low`、`medium`、`high`、`xhigh`、`max` 或空字符串。仅接受 `stop_reason=end_turn` 的回复。

## Python 动作

默认动作空间接受 Python 代码块：

```python
import pyautogui
import pydirectinput
pyautogui.click(960, 540, button="right")
pydirectinput.press("q", duration=0.08)
```

鼠标使用 PyAutoGUI，键盘使用 pydirectinput-rgx。多个块按顺序执行，每块使用独立命名空间。坐标对应未缩放的桌面截图。解析器会在执行前校验整批语法，但不提供 Python 沙箱。

`WAIT` 等待后获取新截图；`DONE` 结束智能体执行，`FAIL` 标记不可完成，两者仍会触发任务评价。DONE/FAIL 必须位于整批最后。

## computer_13 动作

使用 `--action-space computer_13` 选择 JSON 动作：

```json
{"action_type": "CLICK", "parameters": {"x": 960, "y": 540, "button": "right"}}
```

| 动作 | 参数 |
| --- | --- |
| `MOVE_TO` | `x`、`y`；可选 `duration` |
| `CLICK` | 可选 `x`/`y`、`button`、`num_clicks`（1–3） |
| `MOUSE_DOWN`、`MOUSE_UP` | 可选 `button` |
| `RIGHT_CLICK`、`DOUBLE_CLICK` | 可选 `x`/`y` |
| `DRAG_TO` | `x`、`y`；可选 `duration` |
| `SCROLL` | 整数 `dx` 和 / 或 `dy` |
| `TYPING` | `text`；可选 `interval`、`duration` |
| `PRESS` | `key`；可选 `duration` |
| `KEY_DOWN`、`KEY_UP` | `key` |
| `HOTKEY` | 非空 `keys` 列表 |

坐标必须成对提供。回复可以是 JSON 对象或多个对象代码块，不接受 JSON 数组，也兼容平铺参数。WAIT/DONE/FAIL 支持裸文本、代码块标记或动作字典。固定映射见 [computer_13.py](computer_13.py)。

## 观察与动作的时间差

![模型推理期间环境持续变化](../../assets/realtime-interaction.png)

动作依据先前截图生成，执行时游戏仍在推进。上排是场景不变的示意，下排是李青任务的实际交互片段；动作标注来自日志，不表示单个动作的独立效果。

## 流式模式与输出

`prompt-stream` 改变响应传输方式，在完整响应结束后才执行代码。OpenAI 流连接 / 读取失败或缺少完成事件时最多重试两次，等待 1 秒、2 秒；明确的 failed/incomplete/error 事件直接拒绝。SDK 请求重试和一次 OAuth 过期刷新分别处理。不完整尝试不会提交历史或执行动作。

流式尝试诊断以 `request_diagnostic` 事件写入 `trajectory.jsonl`，包含耗时、尝试次数、可用的请求 / 响应 ID、最近事件类型、结果和重试等待。诊断不包含凭据、截图或残缺模型文本。重试可能增加耗时与模型用量。

结果保存到 `results/experiment-<agent>_<model>_<reasoning-effort>/<task.id>/run-*`。参见[结果说明](../../README.zh-CN.md)和[任务目录](../../task/README.zh-CN.md)。

截图、历史和动作设计参考 [OSWorld-V2](https://github.com/xlang-ai/OSWorld-V2)。
