"""Phase 1 AgentCore entry point using Strands Agents SDK.

Provides an interactive conversational agent for creators to set up
their AI assistant profile, upload KB documents, and preview behavior.

Deployment: ARM64 container via AgentCore Runtime.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback

# Basic logging to stdout for container visibility
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

logger.info("AgentCore agent module loading...")

try:
    from strands import Agent
    from strands.models.bedrock import BedrockModel
    from bedrock_agentcore.runtime import BedrockAgentCoreApp

    AGENTCORE_AVAILABLE = True
    logger.info("Strands SDK and AgentCore SDK loaded successfully")
except ImportError as e:
    AGENTCORE_AVAILABLE = False
    logger.error("Failed to import SDK: %s", e)
    traceback.print_exc()

from phase1_agent.prompt.system_prompt import SYSTEM_PROMPT

# Import tool functions
from phase1_agent.tools.create_profile import create_profile
from phase1_agent.tools.update_profile import update_profile
from phase1_agent.tools.upload_document import upload_document
from phase1_agent.tools.ingest_content import ingest_content
from phase1_agent.tools.ingest_url import ingest_url
from phase1_agent.tools.ingest_text_note import ingest_text_note
from phase1_agent.tools.manage_documents import list_documents, delete_document
from phase1_agent.tools.sync_knowledge_base import sync_knowledge_base
from phase1_agent.tools.preview_answer import preview_answer

REGION = os.environ.get("AWS_REGION", "us-west-2")
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

TOOLS = [
    create_profile, update_profile,
    ingest_content, ingest_url, ingest_text_note,
    list_documents, delete_document,
    upload_document, sync_knowledge_base, preview_answer,
]


if AGENTCORE_AVAILABLE:
    logger.info("Initializing Strands Agent with model=%s", MODEL_ID)

    try:
        bedrock_model = BedrockModel(
            model_id=MODEL_ID,
            region_name=REGION,
        )
        agent = Agent(
            model=bedrock_model,
            tools=TOOLS,
            system_prompt=SYSTEM_PROMPT,
        )
        logger.info("Agent created successfully")
    except Exception:
        logger.exception("Failed to create Agent")
        agent = None

    app = BedrockAgentCoreApp()

    @app.entrypoint
    def invoke(payload: dict) -> dict:
        logger.info("Received request: %s", str(payload)[:200])
        if agent is None:
            return {"error": "Agent failed to initialize"}
        query = payload.get("prompt", payload.get("query", ""))
        if not query:
            return {"error": "No prompt provided"}
        logger.info("Processing query: %s", query[:100])
        try:
            response = agent(query)
            result = str(response)
            logger.info("Response generated (%d chars)", len(result))
            return {"result": result}
        except Exception as e:
            logger.exception("Agent invocation failed")
            return {"error": str(e)}

    if __name__ == "__main__":
        logger.info("Starting AgentCore Backend on model=%s region=%s", MODEL_ID, REGION)
        app.run()
else:
    logger.error("AgentCore SDK not available - container will not serve requests")
    if __name__ == "__main__":
        print("AgentCore SDK not installed.")
        sys.exit(1)
