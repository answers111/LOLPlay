# LOL-Play

[English](README.md) | **简体中文**

LOL-Play 是在本机运行的英雄联盟智能体评测项目。它负责准备自定义对局，让视觉智能体操作桌面，并通过 Live Client Data API 对游戏目标评分。项目包含覆盖 36 位英雄的 36 个任务，以及 5 种智能体模式。

## 运行与评分流程

![LOL-Play 运行与评分流程](assets/overview.png)

智能体根据截图生成鼠标和键盘动作；运行器准备对局并执行动作，评价器独立读取 Live Client API 的状态与事件判断目标。图中以 Task035 沃里克为例。

[查看原始矢量图](assets/overview.pdf)

## 运行要求

- Windows、Python 3.10 或更高版本、PowerShell 和可交互的桌面会话。
- 已启动并登录的英雄联盟客户端，且可使用任务需要的英雄和机器人。
- 模型凭据，以及兼容所选智能体协议的接口。

游戏集成依赖 Windows 进程发现和输入接口。macOS 可用于阅读和编辑源码；项目自带的游戏运行器面向 Windows。

## 快速开始

在 Windows 的项目根目录执行：

```powershell
python -m pip install -e ".[responses]"
```

创建本地 `.env` 文件：

```dotenv
OPENAI_API_KEY=your_api_key
# 可选：兼容的 API 地址
# OPENAI_BASE_URL=https://your-endpoint/v1
```

先检查本地配置，再运行任务：

```powershell
python run.py --agent prompt --task task001 --check
python run.py --agent prompt --task task001
```

`--check` 会构造所选智能体和桌面环境，不启动游戏，也不请求模型动作。它检查本地配置，不验证远端模型权限。单任务命令的退出码：0 表示任务成功，1 表示任务未成功，2 表示配置错误。

`python run_single_task.py` 提供相同的单任务命令行入口。安装包名称和 Python 导入名称仍为 `lol-world` 和 `lolworld_env`。

## 智能体

| 命令名 | 模型输出 | 会话与传输方式 |
| --- | --- | --- |
| `prompt` | Python 或 `computer_13` JSON | 最近的截图和文本历史；完整响应 |
| `prompt-stream` | Python 或 `computer_13` JSON | 最近的截图和文本历史；流式传输 |
| `responses` | Responses computer 工具调用 | 服务端 response ID 历史 |
| `responses-stateless` | Responses computer 工具调用 | 完整本地历史；`store=False` |
| `responses-stream` | Responses computer 工具调用 | 完整本地历史；流式传输 |

命令行默认使用 `responses`、模型 `gpt-6.1-sol` 和推理强度 `medium`。这些是代码默认值，实际可用性取决于接口。Prompt 系列在模型名以 `claude-` 开头时选择 Anthropic，其余名称选择 OpenAI Responses。流式智能体在整轮响应完成后执行动作。

使用 Anthropic Prompt 智能体时安装 `.[anthropic]`，配置 `ANTHROPIC_AUTH_TOKEN`（或 `CLAUDE_CODE_OAUTH_TOKEN`）；安装 `.[all]` 可包含两个供应商的依赖。配置和协议详见 [Prompt 智能体说明](agents/prompt_agent/README.zh-CN.md)和 [Responses 智能体说明](agents/openai_responses/README.zh-CN.md)。

## 实时交互

![观察、推理和动作执行期间的游戏变化](assets/realtime-interaction.png)

游戏在模型推理和动作执行期间持续运行，因此动作执行时的场景可能已经不同于最初截图。上排为场景不变的示意，并非暂停游戏实验；下排为李青任务的交互片段，标注为日志中的动作，不用于分离每个动作的效果。

[查看原始矢量图](assets/realtime-interaction.pdf)

## 任务与执行

任务涵盖补刀、购买装备、技能分配、英雄成长、战斗、生存和地图目标。完整目标与时限见[任务目录](task/README.zh-CN.md)。

```powershell
python run.py --agent prompt-stream --action-space computer_13 --task task001
python run.py --agent responses --task task008 --defense magic_resist
python run.py --agent prompt --task task036 --max-steps 100 --output-dir results
python run_all_tasks_sequential.py --agent prompt --start-id 1 --end-id 3 --check
python run_all_tasks_sequential.py --agent prompt --start-id 1 --end-id 3
```

批量运行支持 `prompt` 和 `prompt-stream`，按任务编号顺序执行，每次重新创建任务、智能体和环境对象。

| 单任务参数 | 用途 / 默认值 |
| --- | --- |
| `--model`、`--base-url` | 选择模型，覆盖对应供应商的接口地址 |
| `--env-file` | 本地环境文件，默认为入口脚本旁的 `.env` |
| `--setup-timeout` | 准备阶段时限，默认 600 秒 |
| `--execution-timeout` | 执行时限，默认采用任务时限，不能延长任务期限 |
| `--max-steps` | 最大预测轮数，默认 100 |
| `--position` | `TOP`、`JUNGLE`、`MIDDLE`、`BOTTOM`、`UTILITY` 或 `FILL` |
| `--output-dir` | 覆盖结果根目录，通常为 `results` |
| `--defense` | Task008 装备变体：`armor` 或 `magic_resist` |

各命令支持的完整参数可通过 `python run.py --help` 或 `python run_all_tasks_sequential.py --help` 查看。

准备时间与执行时间分开记录。运行器依次准备游戏、获取截图、请求智能体、执行动作、评估任务、保存结果并尝试退出自定义对局。`DONE` 结束智能体执行，是否成功由任务评价器决定。截止快照任务需要持续运行到规定时间。正在进行的模型请求和 Python 动作块可能延后停止。

准备阶段会设置 Q/W/E/R 普通施法、英雄默认皮肤、召唤师技能和任务符文。普通施法设置在任务结束后保留；第一个符文页会被覆盖并保留页名。执行前会验证所需机器人和游戏状态。

## 任务画面

| **经济 · 辛德拉 · task036**<br>[![经济 · 辛德拉](assets/task-036-syndra.png)](assets/task-036-syndra.png) | **协作 · 璐璐 · task025**<br>[![协作 · 璐璐](assets/task-025-lulu.png)](assets/task-025-lulu.png) | **地图目标 · 沃里克 · task035**<br>[![地图目标 · 沃里克](assets/task-035-warwick.png)](assets/task-035-warwick.png) |
| --- | --- | --- |

截图展示装备购买、机器人协作和地图目标等交互场景，不代表任务已成功。完整示例见[任务说明](task/README.zh-CN.md)。

## 结果文件

```text
results/
  experiment-<agent>_<model>_<reasoning-effort>/
    task_001/
      run-<timestamp>-<identifier>/
        trajectory.jsonl
        model_output.jsonl
        agent_result.json
        evaluation.json
        result.json
        step-*.png
    batches/
      all-tasks-<identifier>/summary.json
```

实际文件取决于执行到哪个阶段。`trajectory.jsonl` 保存执行事件，`model_output.jsonl` 保存接口返回的模型文本；`agent_result.json` 描述执行结果，`evaluation.json` 保存游戏评分和证据，`result.json` 合并两者。评价包含 `target_1`、`target_2` 等独立目标和 `target_summary`；无法确认的目标为 `achieved: null`。批次汇总保存各任务结果及清理失败信息。

## 项目结构

| 路径 | 职责 |
| --- | --- |
| `run.py` | 任务和智能体注册、构造及命令行转发 |
| `run_single_task.py` | 单任务命令行和 `run_single_task()` 函数 |
| `run_all_tasks_sequential.py` | 顺序批量运行和汇总 |
| `runner.py` | 预测与动作循环、时限、输出和评价生命周期 |
| [agents/prompt_agent](agents/prompt_agent/README.zh-CN.md) | 截图转代码 / JSON 智能体及供应商适配 |
| [agents/openai_responses](agents/openai_responses/README.zh-CN.md) | Responses computer 智能体及 OpenAI OAuth 处理 |
| [desktop_env](desktop_env/README.zh-CN.md) | 截图、输入执行和窗口焦点 |
| [lolworld_env](lolworld_env/README.zh-CN.md) | 客户端操作、实时数据和证据解析 |
| [task](task/README.zh-CN.md) | 对局准备、目标和评价器 |
| `examples/initialize_match.py` | 环境操作的组合示例 |

## 扩展项目

智能体实现 `predict(instruction, obs)` 并返回 `(response, actions)`。可选实现 `step(action)`；否则运行器通过 `DesktopEnv.step()` 执行 Python 动作字符串。在 `run.AGENTS` 注册构造函数。

任务继承 `BaseTask`，实现 `setup()` 和 `evaluate()`，定义指令与时限，并将类注册到 `run.TASKS`。环境辅助函数提供客户端操作和证据，各任务自行定义成功规则。

桌面动作在本地进程中执行 Python。凭据应排除在版本管理之外，使用可信智能体，并保持游戏窗口可接收输入。客户端更新可能影响英雄、机器人、装备、符文及事件的兼容性。
