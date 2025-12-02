ACTION_PROMPT = """You are an intelligent assistant responsible for interpreting final user propositions and suggesting or executing actionable steps.

# Propositions

{propositions}

# Task

Based on the above propositions, identify and recommend concrete actions that should be taken. Actions may include, but are not limited to: sending notifications, updating records, triggering workflows, or providing user feedback.

For each proposition, consider:
- What is the most relevant, specific, and helpful action that can be taken?
- Is the action time-sensitive or recurring?
- Who or what should perform the action (user, system, third-party service)?
- Are there any privacy, compliance, or safety considerations?

Return your response as a JSON array, where each item contains:
- `proposition_id`: The ID of the proposition.
- `action`: A concise description of the recommended action.
- `priority`: "high", "medium", or "low" (based on urgency/impact).
- `actor`: Who or what should perform the action.
- `notes`: (Optional) Any special considerations or context.

Example output:
[
  {
    "proposition_id": 1,
    "action": "Send a reminder to review the 'Quarterly Report' document.",
    "priority": "high",
    "actor": "user",
    "notes": "Document was mentioned as urgent."
  },
  {
    "proposition_id": 2,
    "action": "Log user preference for 'Notion' as primary note-taking app.",
    "priority": "medium",
    "actor": "system"
  }
]
"""