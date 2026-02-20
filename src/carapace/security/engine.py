from __future__ import annotations

from pydantic_ai import Agent

from carapace.models import (
    OperationClassification,
    Rule,
    RuleCheckResult,
    RuleMode,
    SessionState,
    UsageTracker,
)

_evaluator_agent: Agent[None, bool] | None = None


def _get_evaluator_agent(model: str) -> Agent[None, bool]:
    global _evaluator_agent
    if _evaluator_agent is None:
        _evaluator_agent = Agent(
            model,
            output_type=bool,
            instructions=(
                "You are a security rule evaluator. You will be given:\n"
                "1. A rule with a trigger condition and an effect description\n"
                "2. The current session state (which rules are activated)\n"
                "3. An operation classification\n\n"
                "Answer True if the rule's effect applies to this operation "
                "(i.e., this operation should be gated/restricted by this rule). "
                "Answer False if the rule's effect does not apply.\n\n"
                "Be precise. For example, if a rule says 'block all write operations' "
                "and the operation is a read, answer False. If the rule says "
                "'block outbound communication' and the operation is writing a local "
                "file, answer False."
            ),
        )
    return _evaluator_agent


def _trigger_is_always(trigger: str) -> bool:
    return trigger.strip().lower() == "always"


async def _check_trigger(
    model: str,
    rule: Rule,
    session_state: SessionState,
    classification: OperationClassification,
    usage_tracker: UsageTracker | None = None,
) -> bool:
    """Check if a rule's trigger condition is newly met."""
    if _trigger_is_always(rule.trigger):
        return True
    if rule.id in session_state.activated_rules:
        return True

    agent = _get_evaluator_agent(model)
    prompt = (
        f'Rule trigger: "{rule.trigger}"\n'
        f"Current operation: {classification.operation_type} "
        f"(categories: {classification.categories}, "
        f"description: {classification.description})\n"
        f"Already activated rules: {session_state.activated_rules}\n\n"
        "Has this trigger condition become true based on the current operation? "
        "Answer True if this operation causes the trigger to be met "
        "(e.g., if the trigger is 'the agent has read content from the internet' "
        "and the operation is read_external, then True). "
        "Answer False otherwise."
    )
    result = await agent.run(prompt)
    if usage_tracker:
        usage_tracker.record(model, "rules", result.usage())
    return result.output


async def _check_effect(
    model: str,
    rule: Rule,
    classification: OperationClassification,
    usage_tracker: UsageTracker | None = None,
) -> bool:
    """Check if a rule's effect applies to this specific operation."""
    agent = _get_evaluator_agent(model)
    prompt = (
        f'Rule effect: "{rule.effect}"\n'
        f"Operation type: {classification.operation_type}\n"
        f"Operation categories: {classification.categories}\n"
        f"Operation description: {classification.description}\n\n"
        "Does this rule's effect restrict/gate this specific operation? "
        "Answer True if the operation falls under what the rule restricts. "
        "Answer False if the operation is not restricted by this rule."
    )
    result = await agent.run(prompt)
    if usage_tracker:
        usage_tracker.record(model, "rules", result.usage())
    return result.output


async def check_rules(
    model: str,
    rules: list[Rule],
    session_state: SessionState,
    classification: OperationClassification,
    usage_tracker: UsageTracker | None = None,
) -> RuleCheckResult:
    result = RuleCheckResult()

    for rule in rules:
        if rule.id in session_state.disabled_rules:
            continue

        trigger_met = await _check_trigger(model, rule, session_state, classification, usage_tracker)

        if trigger_met and rule.id not in session_state.activated_rules and not _trigger_is_always(rule.trigger):
            result.newly_activated_rules.append(rule.id)
            session_state.activated_rules.append(rule.id)

        is_active = _trigger_is_always(rule.trigger) or rule.id in session_state.activated_rules
        if not is_active:
            continue

        effect_applies = await _check_effect(model, rule, classification, usage_tracker)
        if effect_applies:
            result.triggered_rules.append(rule.id)
            result.descriptions.append(f"[{rule.id}] {rule.description.strip()}")
            if rule.mode == RuleMode.approve:
                result.needs_approval = True

    return result
