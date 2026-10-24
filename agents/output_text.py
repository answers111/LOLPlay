"""Preserve model output text blocks and their types in response order."""


def output_text_blocks(value, block_type="text"):
    if callable(getattr(value, "model_dump", None)):
        value = value.model_dump(mode="json")
    elif hasattr(value, "__dict__"):
        value = vars(value)
    blocks = []
    if isinstance(value, list):
        for item in value:
            blocks.extend(output_text_blocks(item, block_type))
    elif isinstance(value, dict):
        block_type = value.get("type", block_type)
        for key, item in value.items():
            if key in {"text", "thinking", "refusal", "reasoning_content", "output_text", "summary"} and isinstance(item, str):
                blocks.append({"type": block_type if key == "text" else key, "text": item})
            elif isinstance(item, (list, dict)) or callable(getattr(item, "model_dump", None)):
                blocks.extend(output_text_blocks(item, block_type))
    return blocks
