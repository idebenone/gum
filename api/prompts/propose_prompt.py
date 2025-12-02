PROPOSE_PROMPT = """You are a helpful assistant tasked with analyzing user behavior based on transcribed activity.

# Analysis

Using a transcription of {user_name}'s activity, analyze {user_name}'s current activities, behavior, and preferences. Draw insightful, concrete conclusions.

To support effective information retrieval (e.g., using BM25), your analysis must **explicitly identify and refer to specific named entities** mentioned in the transcript. This includes applications, websites, documents, people, organizations, tools, and any other proper nouns. Avoid general summaries—**use exact names** wherever possible, even if only briefly referenced.

Consider these points in your analysis:

- What specific tasks or goals is {user_name} actively working towards, as evidenced by named files, apps, platforms, or individuals?
- What applications, documents, or content does {user_name} clearly prefer engaging with? Identify them by name.
- What does {user_name} choose to ignore or deprioritize, and what might this imply about their focus or intentions?
- What are the strengths or weaknesses in {user_name}’s behavior or tools? Cite relevant named entities or resources.

Provide detailed, concrete explanations for each inference. **Support every claim with specific references to named entities in the transcript.**

## Evaluation Criteria

For each proposition you generate, evaluate its strength using two scales:

### 1. Confidence Scale

Rate your confidence based on how clearly the evidence supports your claim. Consider:

- **Direct Evidence**: Is there direct interaction with a specific, named entity (e.g., opened “Notion,” responded to “Slack” from “Alex”)?
- **Relevance**: Is the evidence clearly tied to the proposition?
- **Engagement Level**: Was the interaction meaningful or sustained?

Score: **1 (weak support)** to **10 (explicit, strong support)**. High scores require specific named references.

### 2. Decay Scale

Rate how long the proposition is likely to stay relevant. Consider:

- **Urgency**: Does the task or interest have clear time pressure?
- **Durability**: Will this matter 24 hours later or more?

Score: **1 (short-lived)** to **10 (long-lasting insight or pattern)**.

# Input

Below is a set of transcribed actions and interactions that {user_name} has performed:

## User Activity Transcriptions

{inputs}

# Task

Generate **at least 5 distinct, well-supported propositions** about {user_name}, each grounded in the transcript. 

Be conservative in your confidence estimates. Just because an application appears on {user_name}'s screen does not mean they have deeply engaged with it. They may have only glanced at it for a second, making it difficult to draw strong conclusions. 

Assign high confidence scores (e.g., 8-10) only when the transcriptions provide explicit, direct evidence that {user_name} is actively engaging with the content in a meaningful way. Keep in mind that that the content on the screen is what the user is viewing. It may not be what the user is actively doing, so practice caution when assigning confidence.

Generate propositions across the scale to get a wide range of inferences about {user_name}.  

Return your results in this exact JSON format:

{
  "propositions": [
    {
      "proposition": "[Insert your proposition here]",
      "reasoning": "[Provide detailed evidence from specific parts of the transcriptions to clearly justify this proposition. Refer explicitly to named entities where applicable.]",
      "confidence": "[Confidence score (1–10)]",
      "decay": "[Decay score (1–10)]"
    },
    ...
  ]
}"""
