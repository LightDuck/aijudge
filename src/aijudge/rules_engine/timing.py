def check_missing_timing(trigger_step: int, current_step: int) -> bool:
    """Whether a Quick Effect has missed timing.

    A Quick Effect must be activated at the very next opportunity
    after the event that would trigger it (`trigger_step`). If any
    other step — another chain link resolving, a phase change — has
    passed since then (`current_step` > `trigger_step`), timing is
    missed and the effect can no longer be activated for this trigger.
    """
    if current_step < trigger_step:
        raise ValueError("current_step cannot precede trigger_step")
    return current_step > trigger_step
