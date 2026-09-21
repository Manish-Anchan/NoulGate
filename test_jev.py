from typesafe_sdk import TypeSafeClient, Choice, Score, Noul

client = TypeSafeClient(api_key="TYPESAFE_API_KEY_REDACTED")  # Uses TYPESAFE_API_KEY from env

incoming_ticket = """
I am just checking this 
"""

response = client.system_one(
    state=incoming_ticket,
    questions={
        "category": Choice(
            instructions="Route this support issue to the responsible team.",
            criteria={
                "billing": "Invoices, credit card charges, subscription tiers",
                "infrastructure": "Outages, drops, latency, webhook failures, server 500s",
                "general": "Feature requests, how-to questions, documentation",
            },
        ),
        "incident_level": Score(
            instructions="Grade the severity of this issue.",
            criteria=[
                "P3: Minor inconvenience",
                "P2: Degraded non-critical service with workaround",
                "P1: Critical production data loss or active disruption",
            ],
        ),
        "needs_pagerduty": Noul(
            instructions="Does this require waking up an on-call engineer immediately?"
        ),
    },
)

# Deterministic programmatic branching — no JSON parsing or schema validation:
noul_prob = response.answers["needs_pagerduty"].noul
print(f"Needs PagerDuty probability: {noul_prob:.2f}")

if noul_prob > 0.85:
    severity = response.answers["incident_level"].score  # e.g., 2 (0-indexed)
    team = response.answers["category"].choice  # "infrastructure"
    print(f"🚨 [ALERT TRIGGERED] Team: {team}, Severity Level: {severity}")
else:
    print("Normal routing, no urgent alert required.")
