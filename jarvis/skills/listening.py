"""Jarvis's own listening: mute / go to sleep / wake up, and "what did you do today?". Loaded early so
"go to sleep" is never taken as "open an app called sleep"."""

from .. import actions
from ..brain import Response, skill
from ..state import state


# Muted: Jarvis ignores everything except "Hey Jarvis" and push-to-talk, even with always_listen on.
@skill(r"^(?:please\s+)?(?:mute(?: yourself)?|go to sleep|sleep now|stop listening|don'?t listen|be quiet for a while)"
       r"(?: please| for now| for a while)?$")
def mute_listening(m, brain):
    state.set_muted(True)
    return Response(f"Muted, {brain.title}. Say \"Hey {brain.config.name}\" when you need me.", sleep=True)


@skill(r"^(?:please\s+)?(?:unmute(?: yourself)?|start listening|listen again|you can listen(?: again)?)$")
def unmute_listening(m, brain):
    state.set_muted(False)
    return Response(f"Listening again, {brain.title}.")


@skill(r"\bwhat (?:did|have) you (?:done|do)(?: for me)? today\b", r"\bwhat have you been doing today\b",
       r"\b(?:show|read|tell) me (?:the |your )?(?:action )?log\b", r"^what did you do$")
def did_today(m, brain):
    return Response(actions.summary_today())
