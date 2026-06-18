from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float
    label: str
    source: str
    caveats: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class MinyanOption:
    shul_id: int
    shul_name: str
    address: str
    distance_miles: Optional[float]
    tefillah: Optional[str]
    time: Optional[str]
    location_status: Optional[str]
    source: str
    caveats: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

