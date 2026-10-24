# 英雄联盟客户端与游戏数据操作

[English](README.md) | **简体中文**

`lolworld_env` 提供可组合的客户端操作、Live Client Data 读取和证据解析，仅使用 Python 标准库。导入包不会启动游戏；构造 `LoLWorldClient` 时通过 Windows PowerShell 发现运行中的客户端。

在项目根目录执行 `python -m pip install -e .` 安装。客户端操作要求恰好一个已启动并登录的英雄联盟客户端，实时数据需要运行中的对局。

## 环境在运行流程中的位置

![客户端、智能体与独立评价之间的数据流](../assets/overview.png)

环境包连接客户端并读取游戏状态与事件。截图与桌面动作由桌面环境提供，目标判定由任务评价器负责。

## 示例：准备自定义对局

```python
from lolworld_env import (
    LoLWorldClient, create_custom_lobby, start_champion_select,
    wait_for_phase, wait_for_pick_action, select_champion,
    lock_champion, set_default_skin, wait_for_live_game, validate_live_game,
)

client = LoLWorldClient()
create_custom_lobby(client, lobby_name="Ahri Practice", position="MIDDLE")
start_champion_select(client)
wait_for_phase(client, "ChampSelect", timeout=30)
root, action = wait_for_pick_action(client, timeout=30)
select_champion(client, 103, action_id=action["id"], api_root=root)
lock_champion(client, 103, action_id=action["id"], api_root=root)
set_default_skin(client, 103, api_root=root)
wait_for_phase(client, "InProgress", timeout=120)
data = wait_for_live_game(client, timeout=60)
summary = validate_live_game(
    data, champion_name="Ahri", player_count=1, game_mode="CLASSIC",
)
```

示例展示原子操作的组合。注册任务还会设置召唤师技能、符文、普通施法、所需机器人，并校验初始状态，详见[任务说明](../task/README.zh-CN.md)。

## 客户端操作

| 分组 | 公共函数 |
| --- | --- |
| 队列与房间 | `list_queues`、`find_practice_queue`、`get_lobby`、`create_lobby`、`create_custom_lobby`、`create_practice_lobby` |
| 房间校验与机器人 | `validate_practice_lobby`、`validate_custom_lobby`、`add_custom_bot`、`validate_custom_bot_lobby` |
| 分路与输入设置 | `set_position_preferences`、`set_normal_skill_cast` |
| 英雄选择 | `start_champion_select`、`get_champion_select_session`、`get_local_pick_action`、`wait_for_pick_action`、`get_pickable_champions`、`select_champion`、`lock_champion` |
| 配置 | `set_summoner_spells`、`set_runes`、`set_default_skin` |
| 游戏生命周期 | `wait_for_phase`、`wait_for_live_game`、`validate_live_game`、`validate_roster`、`exit_custom_game` |
| 请求传输 | `LoLWorldClient.request`、`LoLWorldClient.phase`、`ApiError` |

创建房间要求客户端阶段为 `None`。自定义与训练房间使用不同创建函数，开始选人需单独调用。分路偏好不会强制智能体走对应路线。创建辅助函数的次选固定为 `FILL`，`position=None` 跳过偏好设置。

选择和锁定要求存在进行中的本地选人动作，并且英雄可用。D/F 技能和符文在锁定前配置，默认皮肤在锁定后设置。`set_runes()` 覆盖并选中返回的第一个符文页，保留名称；没有第一页或不可编辑时会报错。配置接受四个主系符文、两个副系符文和三个属性碎片。

`set_normal_skill_cast()` 会持久保存 Q/W/E/R 普通施法。等待函数有独立超时，正在进行的 HTTP 请求可能额外耗时最多 10 秒。失败通过异常交给调用方处理。

## 实时数据与证据

```python
from lolworld_env import get_live_data, get_player, get_creep_score, stat_ratio

data = get_live_data()
player = get_player(data)
if player is not None:
    creep_score = get_creep_score(player)
    mana_ratio = stat_ratio(data, "resourceValue", "resourceMax")
```

| 模块 | 职责 / 函数 |
| --- | --- |
| `live_data.py` | 快照校验、玩家 / 英雄 / 补刀 / 时间读取、`item_counts`、`ability_levels`、`stat_value`、`stat_ratio` 和玩家标识 |
| `live_events.py` | 身份映射、`champion_kill_events`、`objective_events`、`turret_identity` |
| `evaluation_state.py` | `capture_evaluation_state`、`capture_event_progress` |
| `validation.py` | `valid_number`、`valid_count`、`is_valid_scores_and_time` |

除 API 读取函数外，解析器处理调用方传入的快照，不决定任务分数。缺失数据与零不同：`item_counts(None)` 返回 `None`，`item_counts([])` 返回空字典。事件归属需要无歧义身份和有效时间戳。起点、目标配置和初始属性基线由调用方提供。

环境包不依赖 `task`。任务类定义目标、时限与成功条件，本包提供操作和证据。

## 独立示例

[examples/initialize_match.py](../examples/initialize_match.py) 在安装包外展示训练对局编排：

```powershell
python examples/initialize_match.py --champion-id 103 --lobby-name "My Practice"
```

完整智能体执行见[项目说明](../README.zh-CN.md)。
