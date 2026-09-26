"""Shut down, restart, sleep and lock the computer.

Destructive actions (shutdown, restart, sleep) always ask for confirmation first.
Set JARVIS_DRY_RUN=1 to print the command instead of running it.
"""

import platform
import subprocess

from ..brain import Response, skill

COMMANDS = {
    "Windows": {
        "shutdown": ["shutdown", "/s", "/t", "30"],
        "restart": ["shutdown", "/r", "/t", "30"],
        "cancel": ["shutdown", "/a"],
        "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
    },
    "Darwin": {
        "shutdown": ["osascript", "-e", 'tell app "System Events" to shut down'],
        "restart": ["osascript", "-e", 'tell app "System Events" to restart'],
        "sleep": ["pmset", "sleepnow"],
        "lock": ["pmset", "displaysleepnow"],
    },
    "Linux": {
        "shutdown": ["shutdown", "-h", "+1"],
        "restart": ["shutdown", "-r", "+1"],
        "cancel": ["shutdown", "-c"],
        "sleep": ["systemctl", "suspend"],
        "lock": ["loginctl", "lock-session"],
    },
}


def run(action: str, brain) -> bool:
    cmd = COMMANDS.get(platform.system(), {}).get(action)
    if cmd is None:
        return False
    if brain.config.dry_run:
        print(f"[dry run] would execute: {' '.join(cmd)}")
        return True
    try:
        subprocess.run(cmd, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _confirmed(action: str, done: str, brain):
    def go() -> Response:
        if run(action, brain):
            return Response(done)
        return Response(f"I wasn't able to {action} the computer, {brain.title}. I may lack the permissions.")

    return go


@skill(r"\b(cancel|abort|stop) (the )?(shut ?down|restart|reboot)\b")
def cancel(m, brain):
    if run("cancel", brain):
        return Response(f"Shutdown cancelled, {brain.title}.")
    return Response("There's nothing I can cancel on this system.")


@skill(r"\b(shut ?down|turn off|power off|switch off)\b.*\b(computer|pc|laptop|system|machine|mac)\b",
       r"^(shut ?down|power off)$")
def shutdown(m, brain):
    return Response(
        f"Are you sure you want me to shut down the computer, {brain.title}?",
        on_confirm=_confirmed("shutdown", f"Shutting down. Goodbye, {brain.title}.", brain),
    )


@skill(r"\b(restart|reboot)\b")
def restart(m, brain):
    return Response(
        f"Shall I restart the computer, {brain.title}?",
        on_confirm=_confirmed("restart", "Restarting now. See you on the other side.", brain),
    )


@skill(r"\b(put|send) (the |my )?(computer|pc|laptop|system|mac) to sleep\b", r"^(sleep|hibernate)( mode)?$")
def sleep(m, brain):
    return Response(
        f"Put the computer to sleep, {brain.title}?",
        on_confirm=_confirmed("sleep", "Going to sleep.", brain),
    )


@skill(r"\block (the |my )?(computer|pc|laptop|screen|system|mac)\b", r"^lock( it)?$")
def lock(m, brain):
    if run("lock", brain):
        return Response(f"Locked, {brain.title}.")
    return Response(f"I couldn't lock the screen, {brain.title}.")
