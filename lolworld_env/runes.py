"""Configure and select the first existing rune page without creating pages."""


def set_runes(client, *, primary_style_id, sub_style_id, selected_perk_ids):
    """Overwrite the first returned page, preserving its name, and confirm it.

    selected_perk_ids contains four primary runes, two secondary runes, and
    three stat shards, in that order. The client validates rune availability.
    """
    perks = list(selected_perk_ids)
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
           for value in (primary_style_id, sub_style_id, *perks)):
        raise ValueError("Rune style and perk IDs must be positive integers")
    if primary_style_id == sub_style_id:
        raise ValueError("Primary and secondary rune styles must differ")
    if len(perks) != 9:
        raise ValueError("Exactly nine rune and stat shard IDs are required")
    pages = client.request("GET", "/lol-perks/v1/pages")
    if not pages:
        raise RuntimeError("No rune pages available")
    page = pages[0]
    if not page.get("isEditable"):
        raise RuntimeError("First rune page is not editable")
    config = {"name": page["name"], "primaryStyleId": primary_style_id,
              "subStyleId": sub_style_id, "selectedPerkIds": perks, "current": True}
    client.request("PUT", f"/lol-perks/v1/pages/{page['id']}", config)
    client.request("PUT", "/lol-perks/v1/currentpage", page["id"])
    current_page = client.request("GET", "/lol-perks/v1/currentpage")
    if (current_page.get("id") != page["id"]
            or any(current_page.get(key) != config[key] for key in
                   ("primaryStyleId", "subStyleId", "selectedPerkIds"))):
        raise RuntimeError("Client did not confirm the requested runes")
    return current_page
