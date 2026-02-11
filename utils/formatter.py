def format_seconds_to_human_readable(seconds: int) -> str:
    """
    Converts a duration in seconds into a friendly string (e.g., '1 hour, 30 minutes').

    Args:
        seconds (int): The duration in seconds.

    Returns:
        str: Human-readable time string.
    """
    seconds = int(seconds)
    if seconds < 0:
        seconds = 0

    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    parts = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
    if secs or not parts:
        parts.append(f"{secs} second{'s' if secs != 1 else ''}")

    return ', '.join(parts)
