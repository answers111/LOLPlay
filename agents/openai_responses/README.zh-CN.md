# Responses computer 智能体

[English](README.md) | **简体中文**

本包提供三种基于截图和 Responses computer 工具调用操作游戏的智能体。共用运行器负责任务准备、执行时限、日志、评分和对局清理。

## 智能体模式

| 命令名 | 类 | 历史与传输方式 |
| --- | --- | --- |
| `responses` | `OpenAIResponseAgent` | 通过 `previous_response_id` 使用服务端历史 |
| `responses-stateless` | `OpenAIResponseStatelessAgent` | 完整内存历史，`store=False` |
| `responses-stream` | `OpenAIResponseStreamingAgent` | 无服务端状态历史，流式响应 |

无状态模式的历史包含模型输出和匹配的工具截图反馈，`reset()` 会清空历史。请求体随对话增长。流式模式等待完整响应后再解析和执行动作，不执行中途输出。

## 配置与使用

在项目根目录执行：

```powershell
python -m pip install -e ".[responses]"
python run.py --agent responses --task task001 --check
python run.py --agent responses --task task001
python run.py --agent responses-stateless --task task001
python run.py --agent responses-stream --task task001
```

在本地 `.env` 中设置 `OPENAI_API_KEY`，可选配置 `OPENAI_BASE_URL` 或传入 `--base-url`。接口和模型需要支持 Responses computer 工具协议。代码默认使用 `gpt-6.1-sol`、推理强度 `medium`，应根据实际接口选择可用值。`--check` 检查本地构造，不启动游戏，也不验证远端权限。

### OAuth 凭据

`OPENAI_OAUTH_CREDENTIALS` 可指向外部提供的凭据 JSON 文件，优先于 API Key。文件需要按 [oauth.py](oauth.py) 的要求提供 `access_token`、`refresh_token`、`client_id`、`saved_at` 和 `expires_in`。

辅助模块在请求前检查有效期，剩余不足 60 秒时刷新，对 token 过期的 401 刷新并重试一次。凭据更新采用原子保存，共用文件的进程会串行刷新。刷新被拒绝后需要重新授权，不会回退到 API Key 计费。凭据应保存在仓库外。本项目读取凭据，不提供交互式登录流程。

## 观察与动作的时间差

![模型推理期间环境持续变化](../../assets/realtime-interaction.png)

动作依据先前截图生成，执行时游戏仍在推进。上排是场景不变的示意，下排是李青任务的实际交互片段；动作标注来自日志，不表示单个动作的独立效果。

## 执行与结果

智能体将结构化鼠标和键盘动作转换成桌面代码。PyAutoGUI 负责移动、拖拽和滚动，pydirectinput-rgx 负责点击和扫描码键盘。[桌面环境](../../desktop_env/README.zh-CN.md)执行动作并返回截图。

执行期限由任务定义。运行器在请求和动作前检查停止条件，进行中的请求可能延后停止。各模式统一使用以下结果结构：

```text
results/experiment-<agent>_<model>_<reasoning-effort>/<task.id>/run-*/
```

执行状态和游戏成功分别记录。文件说明见[项目说明](../../README.zh-CN.md)，评分规则见[任务目录](../../task/README.zh-CN.md)。

交互设计参考 [OSWorld-V2](https://github.com/xlang-ai/OSWorld-V2)，实现位于 [gpt_response_api.py](gpt_response_api.py)。
