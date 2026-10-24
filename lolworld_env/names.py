"""English name conversion helpers for League of Legends."""

# only for non English version
import json
import urllib.request

VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def add_english_names(data: dict) -> None:
    """Replace localized display names using  Riot's English Data Dragon files."""
    version = get_json(VERSIONS_URL)[0]
    base = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/"
    items = get_json(base + "item.json")["data"]
    summoners = get_json(base + "summoner.json")["data"]
    summoner_names = {value["id"]: value["name"] for value in summoners.values()}
    rune_trees = get_json(base + "runesReforged.json")
    rune_names = {}
    for tree in rune_trees:
        rune_names[tree["id"]] = tree["name"]
        for slot in tree["slots"]:
            for rune in slot["runes"]:
                rune_names[rune["id"]] = rune["name"]

    champion_data = {}
    for player in data.get("allPlayers", []):
        raw = player.get("rawChampionName", "")
        champion_id = raw.removeprefix("game_character_displayname_")
        if not champion_id:
            continue
        if champion_id not in champion_data:
            champion_data[champion_id] = get_json(
                base + f"champion/{champion_id}.json"
            )["data"][champion_id]
        champion = champion_data[champion_id]
        player["championName"] = champion["name"]
        player["englishChampionName"] = champion["name"]
        for skin in champion.get("skins", []):
            if skin.get("num") == player.get("skinID"):
                player["skinName"] = skin["name"]
                break
        for item in player.get("items", []):
            name = items.get(str(item.get("itemID")), {}).get("name")
            if name:
                item["displayName"] = name
                item["englishDisplayName"] = name
        for rune in player.get("runes", {}).values():
            if isinstance(rune, dict) and rune.get("id") in rune_names:
                rune["displayName"] = rune_names[rune["id"]]
        for spell in player.get("summonerSpells", {}).values():
            raw_spell = spell.get("rawDisplayName", "")
            spell_id = raw_spell.removeprefix("GeneratedTip_SummonerSpell_").removesuffix("_DisplayName")
            if spell_id in summoner_names:
                spell["displayName"] = summoner_names[spell_id]

    active = data.get("activePlayer", {})
    active_id = active.get("riotId") or active.get("summonerName")
    active_player = next(
        (p for p in data.get("allPlayers", []) if active_id in (p.get("riotId"), p.get("summonerName"))),
        None,
    )
    if active_player:
        champion_id = active_player["rawChampionName"].removeprefix("game_character_displayname_")
        champion = champion_data.get(champion_id, {})
        ability_names = {spell["id"]: spell["name"] for spell in champion.get("spells", [])}
        if champion.get("passive"):
            ability_names[champion_id + "Passive"] = champion["passive"]["name"]
        for ability in active.get("abilities", {}).values():
            if ability.get("id") in ability_names:
                ability["displayName"] = ability_names[ability["id"]]
    for rune in active.get("fullRunes", {}).get("generalRunes", []):
        if rune.get("id") in rune_names:
            rune["displayName"] = rune_names[rune["id"]]
    for key in ("keystone", "primaryRuneTree", "secondaryRuneTree"):
        rune = active.get("fullRunes", {}).get(key, {})
        if rune.get("id") in rune_names:
            rune["displayName"] = rune_names[rune["id"]]


