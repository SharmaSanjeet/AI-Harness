import re
from datetime import datetime

CRM = {
    "Acme Corp": {
        "name": "Jane Doe",
        "title": "VP of Engineering",
        "contact": "jane@acme.com",
        "tier": "gold",
    },
    "BlueSky Ltd": {
        "name": "Bob Smith",
        "title": "Head of IT",
        "contact": "bob@bluesky.io",
        "tier": "silver",
    },
}

ENRICHMENT = {
    "Acme Corp": {
        "industry": "AI Software",
        "size": "200 employees",
        "recent_news": "Launched a new GenAI product last month",
    },
    "BlueSky Ltd": {
        "industry": "Cloud Services",
        "size": "80 employees",
        "recent_news": "Expanded into the EU market",
    },
}

ACTIVITY_LOG = []


def sanitize_company(company: str) -> str:
    """Strip characters commonly used to smuggle prompt-injection payloads."""
    company = (company or "").strip()
    company = re.sub(r"[^\w\s&.'()-]", "", company)
    return company[:60]


def get_contact(company: str) -> dict:
    return CRM.get(company, {})


def enrich_company(company: str) -> dict:
    return ENRICHMENT.get(company, {})


def log_activity(company: str, note: str) -> dict:
    if company not in CRM:
        return {"ok": False, "error": f"{company!r} is not in the CRM"}
    entry = {
        "company": company,
        "note": note,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    ACTIVITY_LOG.append(entry)
    return {"ok": True, "log": f"{note} saved for {company}"}
