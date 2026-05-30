"""Constants for Dynamic Central Audio."""

DOMAIN = "dynamic_central_audio"

ENTRY_TYPE_SYSTEM = "system"
ENTRY_TYPE_ZONE = "zone"

# Poll interval — primarily event-driven; this is the fallback
SCAN_INTERVAL_SECONDS = 60

# Source defaults
DEFAULT_ACTIVE_STATE = "playing"
DEFAULT_GATE_STATE = "on"
DEFAULT_BASE_VOLUME = 0.70
DEFAULT_PRIORITY = 5
DEFAULT_SOURCE_OFF_DELAY = 300  # 5 min — delay before zones shut off when source stops

# Zone defaults
DEFAULT_OFF_DELAY = 600          # 10 min — delay before zone shuts off when room empties
DEFAULT_RESTORE_DELAY = 300      # 5 min — delay before ATV exclusion restore (occupied condition)
DEFAULT_VOLUME_OFFSET = 0.0

# Volume offset bounds
VOLUME_OFFSET_MIN = -0.30
VOLUME_OFFSET_MAX = 0.30
VOLUME_OFFSET_STEP = 0.01

# ATV restore conditions
RESTORE_ANY_STOPPED = "any_stopped"
RESTORE_ALL_STOPPED = "all_stopped"
RESTORE_OCCUPIED = "occupied"
RESTORE_CONDITIONS = [RESTORE_ANY_STOPPED, RESTORE_ALL_STOPPED, RESTORE_OCCUPIED]

# Zone status values
STATUS_FOLLOWING = "following"
STATUS_STANDBY = "standby"
STATUS_ATV_OVERRIDE = "atv_override"
STATUS_FOLLOW_ME_OFF = "follow_me_off"
STATUS_SYSTEM_INACTIVE = "system_inactive"
STATUS_NO_SYSTEM = "no_system"
STATUS_IDLE = "idle"

# System routing modes
ROUTING_NONE = "none"
