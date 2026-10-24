# Gameplay tasks

**English** | [简体中文](README.zh-CN.md)

The task package defines 36 champion-specific custom-game objectives. Each `TaskNNN(BaseTask)` owns its preparation, instruction, execution limit, and evaluator. Importing tasks does not start gameplay.

## Running a task

From the project root, after configuring an agent:

```powershell
python run.py --agent prompt --task task001 --check
python run.py --agent prompt --task task001
python run.py --agent responses --task task008 --defense magic_resist
python run_all_tasks_sequential.py --agent prompt --start-id 1 --end-id 3
```

The CLI uses `task001` through `task036`. Task metadata and result folders use `task_001` through `task_036`.

## Representative task scenes

| **Economy · Syndra · task036**<br>[![Economy · Syndra](../assets/task-036-syndra.png)](../assets/task-036-syndra.png) | **Development · Ahri · task009**<br>[![Development · Ahri](../assets/task-009-ahri.png)](../assets/task-009-ahri.png) | **Sustain · Brand · task016**<br>[![Sustain · Brand](../assets/task-016-brand.png)](../assets/task-016-brand.png) |
| --- | --- | --- |

| **Combat · Darius · task022**<br>[![Combat · Darius](../assets/task-022-darius.png)](../assets/task-022-darius.png) | **Cooperation · Lulu · task025**<br>[![Cooperation · Lulu](../assets/task-025-lulu.png)](../assets/task-025-lulu.png) | **Map objectives · Warwick · task035**<br>[![Map objectives · Warwick](../assets/task-035-warwick.png)](../assets/task-035-warwick.png) |
| --- | --- | --- |

These scenes illustrate economy, development, sustain, combat, cooperation, and map objectives. Click a screenshot for the original resolution. Screenshots illustrate interaction, not necessarily success; task evaluators define the success conditions.

## Task catalog

CS means the API's total creep score, including minions and monsters. All listed conditions for a task are required. Item conditions refer to current inventory; growth is measured against the successful setup snapshot. The linked modules define the exact evaluator rules.

| Task / source | Champion | Success conditions | Minutes |
| --- | --- | --- | --- |
| [task001](task_001.py) | Caitlyn | CS ≥ 30 | 10 |
| [task002](task_002.py) | Lee Sin | Personally kill the first elemental dragon | 10 |
| [task003](task_003.py) | Ziggs | Destroy the enemy mid outer turret | 10 |
| [task004](task_004.py) | Sion | At deadline: maximum health ≥ 2000 | 10 |
| [task005](task_005.py) | Varus | CS ≥ 10; Pickaxe (1037) | 7 |
| [task006](task_006.py) | Mordekaiser | CS ≥ 10; Amplifying Tome (1052) and Ruby Crystal (1028) | 8 |
| [task007](task_007.py) | Sona | Level ≥ 4; Sapphire Crystal (1027), Boots (1001); current gold ≥ 300 | 8 |
| [task008](task_008.py) | Rammus | Level ≥ 3; selected defense component and Boots (1001) | 8 |
| [task009](task_009.py) | Ahri | CS ≥ 10; level ≥ 4; Q2/W1/E1/R0 | 7 |
| [task010](task_010.py) | Kayle | CS ≥ 10; level ≥ 6; R ≥ 1 | 9 |
| [task011](task_011.py) | Garen | CS ≥ 10; level ≥ 4; Q/E ≥ 1; W = 0 | 7 |
| [task012](task_012.py) | Veigar | CS ≥ 10; ability power growth ≥ 40 | 8 |
| [task013](task_013.py) | Cho'Gath | Level ≥ 6; R ≥ 1; maximum health growth ≥ 350 | 9 |
| [task014](task_014.py) | Ashe | CS ≥ 20; Dagger (1042); attack speed ≥ 0.9/s | 8 |
| [task015](task_015.py) | Leona | Level ≥ 4; Cloth Armor (1029) and Null-Magic Mantle (1033) | 8 |
| [task016](task_016.py) | Brand | At deadline: CS ≥ 20; mana ≥ 50% | 8 |
| [task017](task_017.py) | Dr. Mundo | At deadline: CS ≥ 20; alive; health ≥ 80% | 8 |
| [task018](task_018.py) | Soraka | Level ≥ 5; CS < 20 | 8 |
| [task019](task_019.py) | Lux | CS ≥ 20; W = 0 | 8 |
| [task020](task_020.py) | Kennen | CS ≥ 20; level ≥ 4; no deaths | 8 |
| [task021](task_021.py) | Sivir | At deadline: CS ≥ 10; no deaths | 8 |
| [task022](task_022.py) | Darius | Personally kill the specified enemy bot ≥ 1 time; deaths ≤ 1 | 9 |
| [task023](task_023.py) | Tristana | CS ≥ 10; personally kill specified bot ≥ 1 time; Pickaxe (1037) | 9 |
| [task024](task_024.py) | Malphite | Level ≥ 5; deaths ≤ 1; Cloth Armor (1029) and Boots (1001) | 9 |
| [task025](task_025.py) | Lulu | Assist allied Ashe in ≥ 1 kill; deaths ≤ 1 | 10 |
| [task026](task_026.py) | Nautilus | Assist allied Ashe in ≥ 2 kills; level ≥ 5 | 10 |
| [task027](task_027.py) | Yorick | Enemy top outer turret, then top inner turret | 20 |
| [task028](task_028.py) | Jax | Enemy top and mid outer turrets, in either order | 20 |
| [task029](task_029.py) | Annie | Personally kill Soraka ≥ 2 times; deaths ≤ 1 | 10 |
| [task030](task_030.py) | Talon | Personally kill Ashe ≥ 1 time; no deaths | 5 |
| [task031](task_031.py) | Katarina | Personally kill Miss Fortune and Soraka ≥ 1 time each; deaths ≤ 2 | 10 |
| [task032](task_032.py) | Xin Zhao | ≥ 3 distinct kill participations, including a personal kill and an assist to Ashe; deaths ≤ 2 | 12 |
| [task033](task_033.py) | Draven | At deadline: CS ≥ 40; current gold ≥ 1500; alive | 10 |
| [task034](task_034.py) | Ryze | At deadline: level ≥ 7; CS ≥ 40; mana ≥ 60%; alive | 10 |
| [task035](task_035.py) | Warwick | Personally kill ≥ 1 Void Grub, then destroy enemy top outer turret | 12 |
| [task036](task_036.py) | Syndra | Hold Lost Chapter (3802) in inventory | 7 |

## Preparation and game settings

Tasks create a Summoner's Rift custom game and validate the expected champion, map, mode, roster, and initial data. Setup time is excluded from the execution budget. Each module defines its lane, summoner spells, runes, and lobby name.

Preparation enables normal Q/W/E/R casting and sets the champion's default skin. It overwrites and selects the first rune page while retaining its name; an absent or noneditable page is an error. The normal-casting setting persists after the run. Position preferences can be overridden with `--position` but do not force in-game routing.

Task008 defaults to Cloth Armor (1029) and Boots (1001). `--defense magic_resist` substitutes Null-Magic Mantle (1033) for Cloth Armor. The Python equivalent is `Task008(defense="magic_resist")`.

Tasks021–024 use an enemy Soraka bot. Tasks025–026 use allied Ashe against Miss Fortune and Soraka. Tasks029–032 use their specified combat bots; Task032 places the three bots in bottom lane while the player jungles. Required bots use `RSBEGINNER`; unavailable or unconfirmed bots cause setup to fail.

## Scoring and deadlines

- The evaluator returns `success`, `score`, `reason`, and available game evidence. `DONE` alone does not establish success.
- Tasks004, 016, 017, 021, 033, and 034 preserve a snapshot at their execution deadline. Ending early does not satisfy their deadline requirement.
- The runner defaults to each task's limit. `--execution-timeout` can shorten execution but cannot extend the objective deadline. Preparation uses a separate timeout.
- State conditions use the evaluation snapshot; event conditions require valid evidence within the task window. A late model response or evaluation sample does not by itself make a task fail, but cannot prove an event occurred on time.
- Tower goals allow allied minions to land the last hit. Task027 requires strict outer-before-inner ordering. Task035 requires a personal `HordeKill` before the target tower event; Herald kills and assists do not substitute.
- Combat goals use validated `ChampionKill` events and unambiguous player identities. Task031 requires both enemies; Task032 counts a shared event once and requires both a personal kill and an assist to allied Ashe.
- Missing or invalid evidence is not treated as zero. API connection errors propagate to the runner. Current inventory is distinct from purchase history; sold or upgraded items do not meet an inventory requirement.

CS thresholds follow the API counts directly, using multiples of ten for lower bounds. Soraka's constraint is strictly CS < 20. Client versions may change event availability and data behavior; evaluators only score the evidence they can validate.

## Python interface

```python
from task import Task001

task = Task001(trajectory="results")
task.setup()
# An agent operates the game using task.instruction.
result = task.evaluate()
```

For lifecycle management, use `run_single_task(task, agent, env, ...)` from [run_single_task.py](../run_single_task.py). It prepares the game, runs the agent, saves evaluation, and invokes cleanup when configured.

## Result evidence

The common runner saves execution and evaluation separately in `results/experiment-<agent>_<model>_<reasoning-effort>/<task.id>/run-*`. Evaluation can include level, CS, items, gold, abilities, champion stats, raw and qualifying events, and setup/execution timings.

Numbered `target_1`, `target_2`, etc. expose each independent condition with `expected`, `actual`, `operator`, and `achieved`. Values are true, false, or null for insufficient evidence. `target_summary` counts achieved, unmet, and unknown targets. These fields describe progress toward objectives; the evaluator's overall `success` and `reason` remain authoritative.

See the [project guide](../README.md) and [environment operations](../lolworld_env/README.md).
