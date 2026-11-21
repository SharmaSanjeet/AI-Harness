import json
import os

# The host machine's NO_PROXY contains "[::1]", which makes httpx (and the ollama
# client built on it) fail with InvalidURL — normalize before anything imports httpx.
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

from pathlib import Path

import re

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_ollama import ChatOllama

import crm

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
GHOSTWRITER_MODEL = os.getenv("GHOSTWRITER_MODEL", OLLAMA_MODEL)

# Note: we deliberately do NOT use langchain's built-in create_agent/LangGraph here —
# their compiled ormsgpack wheel is blocked by WDAC on this host. The loop below is
# the same ReAct-style architecture (think -> act -> observe) written out explicitly.
router_llm = ChatOllama(
    model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL, temperature=0.1, keep_alive="30m"
)
ghostwriter_llm = ChatOllama(
    model=GHOSTWRITER_MODEL,
    base_url=OLLAMA_BASE_URL,
    temperature=0.7,
    num_predict=300,
    keep_alive="30m",
)


@tool
def crm_get_contact(company: str) -> dict:
    """Look up a company's contact in the CRM. Returns name, title, email, and customer tier."""
    record = crm.get_contact(company.strip())
    if not record:
        return {"ok": False, "error": f"No CRM record found for {company!r}"}
    return {"ok": True, **record}


@tool
def enrich_company(company: str) -> dict:
    """Research a company: industry, employee size, and recent news."""
    data = crm.enrich_company(company.strip())
    if not data:
        return {"ok": False, "error": f"No enrichment data available for {company!r}"}
    return {"ok": True, **data}


@tool
def generate_email(
    company: str,
    contact_name: str,
    contact_email: str,
    industry: str,
    recent_news: str,
) -> str:
    """Draft a short personalized sales outreach email. Pass the contact and enrichment data you collected from the earlier steps, exactly as received."""
    prompt = (
        f"Write a short personalized sales outreach email to {contact_name} "
        f"({contact_email}) at {company}.\n"
        f"Industry: {industry}\n"
        f"Recent news: {recent_news}\n\n"
        "Rules:\n"
        "- Professional but friendly tone, 120 words max\n"
        "- Open by referencing the recent news\n"
        "- One call to action: a 15-minute intro call\n"
        "- Sign off with [Your Name]\n\n"
        "Return ONLY the email in this exact format:\n"
        "Subject: <subject line>\n\n<body>"
    )
    return _clean_email_text(ghostwriter_llm.invoke(prompt).content)


def _clean_email_text(text: str) -> str:
    # Small local models occasionally emit stray XML/HTML wrappers around the draft
    text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)
    return text.strip()


@tool
def crm_log_activity(company: str, note: str) -> dict:
    """Log an activity note for a company in the CRM. Call once after the email draft is created, with a one-line summary."""
    return crm.log_activity(company.strip(), note)


SYSTEM_PROMPT = """You are a sales outreach agent. For each company you are given, follow this workflow exactly, in order:
1. crm_get_contact — look up the contact.
2. enrich_company — research industry, size, and recent news.
3. generate_email — draft the outreach email using the contact and enrichment values you received. Pass them exactly as received.
4. crm_log_activity — log a one-line note, e.g. "Generated outreach email draft for <company>".

Hard rules:
- DRAFT ONLY. You must never say an email was sent.
- Call one tool at a time, wait for its result, then continue.
- Pass exact values from earlier tool results; never invent contact details.
- If a step fails because the company is unknown, stop and explain.
- When all steps are done, reply with a short summary for the user that includes the email draft."""

tools = [crm_get_contact, enrich_company, generate_email, crm_log_activity]
TOOLS_BY_NAME = {t.name: t for t in tools}
router_with_tools = router_llm.bind_tools(tools)

STEP_LABELS = {
    "crm_get_contact": "CRM lookup",
    "enrich_company": "Company enrichment",
    "generate_email": "Email drafting",
    "crm_log_activity": "CRM logging",
}

MAX_STEPS = 8


def run_outreach(company: str) -> dict:
    messages = [
        ("system", SYSTEM_PROMPT),
        (
            "user",
            f"Create a personalized sales outreach email for {company} "
            "and log the activity in the CRM.",
        ),
    ]

    steps = []
    email_draft = None
    log_confirmation = None

    for _ in range(MAX_STEPS):
        ai_message = router_with_tools.invoke(messages)
        messages.append(ai_message)

        if not ai_message.tool_calls:
            break

        for call in ai_message.tool_calls:
            name = call["name"]
            fn = TOOLS_BY_NAME.get(name)
            if fn is None:
                output = {"ok": False, "error": f"Unknown tool {name!r}"}
            else:
                try:
                    output = fn.invoke(call["args"])
                except Exception as exc:
                    output = {"ok": False, "error": str(exc)}

            content = output if isinstance(output, str) else json.dumps(output, default=str)
            messages.append(
                ToolMessage(content=content, tool_call_id=call["id"], name=name)
            )

            steps.append(
                {
                    "tool": name,
                    "label": STEP_LABELS.get(name, name),
                    "args": call["args"],
                    "result": output,
                }
            )
            if name == "generate_email" and isinstance(output, str):
                email_draft = output
            elif name == "crm_log_activity" and isinstance(output, dict):
                log_confirmation = output.get("log") or output.get("error")

    summary = ai_message.content
    if not isinstance(summary, str):
        summary = json.dumps(summary, default=str)

    return {
        "company": company,
        "steps": steps,
        "email": email_draft,
        "log": log_confirmation,
        "summary": summary,
    }
