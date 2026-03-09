from alara.agents.base import BaseAgent


class WritingAgent(BaseAgent):
    name = "writing"
    description = "Writes and edits creative content"
    capabilities = ["document", "filesystem"]

    system_prompt = """
    You are the Writing Agent for ALARA.
    You specialize in creative and professional writing.

    Your strengths:
    - Creative writing (stories, essays, poetry)
    - Professional writing (emails, reports, proposals)
    - Editing and rewriting existing content
    - Adapting tone and style to context
    - Structuring long-form content

    When planning:
    - Use create_file for plain text output
    - Use create_word_doc for formatted documents
    - Use create_markdown for structured content
    - Always save output to a file

    You have access to: document operations, filesystem
    """

    def can_handle(self, goal: str, scope: str) -> bool:
        writing_keywords = [
            "write", "draft", "compose", "create a story",
            "essay", "poem", "blog post", "article",
            "email", "letter", "rewrite", "edit",
            "creative", "fiction", "narrative", "content"
        ]
        
        goal_lower = goal.lower()
        return any(keyword in goal_lower for keyword in writing_keywords)
