"""Deprecated: MedWeave now uses OpenAI by default.

This module is kept only so older imports do not break. Use
`medweave_core.harmonizer.llm_openai` for new work.
"""

raise ImportError("Anthropic integration was replaced by OpenAI. Import medweave_core.harmonizer.llm_openai instead.")
