"""Pure identity-domain presentation rules."""


def get_service_label(service: str) -> tuple[str, str]:
    """Return the display name and icon for a media service."""
    service_name = service.upper()
    service_emoji = "🎬" if service == "plex" else "📺"
    return service_name, service_emoji
