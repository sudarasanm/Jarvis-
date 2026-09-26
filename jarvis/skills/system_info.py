"""Battery, CPU and memory status (requires psutil)."""

from ..brain import Response, skill


@skill(r"\b(system|computer) (status|report|health)\b", r"\bbattery\b", r"\b(cpu|memory|ram) usage\b")
def status(m, brain):
    try:
        import psutil
    except ImportError:
        return Response("I need the psutil package to check system status. Try pip install psutil.")
    parts = [
        f"CPU at {round(psutil.cpu_percent(interval=0.5))} percent",
        f"memory at {round(psutil.virtual_memory().percent)} percent",
    ]
    battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if battery is not None:
        state = "charging" if battery.power_plugged else "on battery"
        parts.append(f"battery at {round(battery.percent)} percent and {state}")
    return Response(", ".join(parts).capitalize() + ".")
