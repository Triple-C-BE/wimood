def format_seconds_to_human_readable(seconds: int) -> str:
    """
    Converts a duration in seconds into a friendly string (e.g., '1 hour' or '30 minutes').

    Args:
        seconds (int): The duration in seconds.

    Returns:
        str: Human-readable time string.
    """
    if seconds >= 3600 and seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''}"
    elif seconds >= 60 and seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''}"
    else:
        return f"{seconds} second{'s' if seconds > 1 else ''}"