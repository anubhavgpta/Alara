from alara.agents.base import BaseAgent


class DocumentAgent(BaseAgent):
    name = "document"
    description = "Creates and edits documents"
    capabilities = ["document", "filesystem"]

    system_prompt = """
    You are the Document Agent for ALARA.
    You specialize in creating and editing documents.

    Your strengths:
    - Creating professional Word documents (.docx)
    - Building PowerPoint presentations (.pptx)
    - Writing and editing Markdown files (.md)
    - Creating and reading PDFs
    - Editing plain text files

    When planning:
    - Use create_word_doc for .docx files
    - Use create_powerpoint for .pptx files
    - Use create_pdf for .pdf files
    - Use create_markdown for .md files
    - Always verify the file was created at the end

    You have access to: document operations, filesystem
    """

    def can_handle(self, goal: str, scope: str) -> bool:
        document_keywords = [
            "word", "docx", "document", "powerpoint",
            "pptx", "presentation", "slides", "pdf",
            "markdown", "readme", "report", "essay",
            "letter", "memo", "draft", "write a doc",
            "create a doc", "edit a doc"
        ]
        
        goal_lower = goal.lower()
        return any(keyword in goal_lower for keyword in document_keywords)
