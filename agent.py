"""Larkspur disruption agent. This is the file you build.

It runs right now, and it is wrong in four places. The trace shows each one
before the code does, so read the trace first:

    python3 run.py K7PQ2M --trace

Where you edit:   grep -n '✏' agent.py   (six marks, one per place)
Steps and gates:  https://anthropicpartnerbasecamp.bts.com/
"""
from __future__ import annotations
from typing import Any, Dict, List
from support import (MODEL, SYSTEM_PROMPT, call_local, execute_tool, mcp_client,
                     new_session, next_available_day, record_tool_result,
                     runtime_preamble)

MAX_TOOL_CALLS = 8  # Larkspur's own build capped the loop here; then a human takes over.

TONE_ADDENDUM = ""                       # ✏️ Build 4, step 4.1, intelligence goal
from support.mock_backend import load_policy


def _band_for(policy, status, delay_minutes):
    if status == "CANCELLED":
        return "CXL"
    if status == "DIVERTED":
        return "DIV"
    for b in policy["delay_bands"]:
        if b["band"] in ("CXL", "DIV"):
            continue
        hi = b["max_minutes"]
        if b["min_minutes"] <= delay_minutes and (hi is None or delay_minutes <= hi):
            return b["band"]
    return None


def care_entitlements(cause_code, status, delay_minutes=0, overnight=False,
                      wait_minutes_for_alternative=None, loyalty_tier=None):
    """Meal / hotel / ground care from disruption_policy.json. No booking needed."""
    policy = load_policy()
    if cause_code not in policy["cause_classes"]:
        return {"error": "cause_code must be one of %s" % sorted(policy["cause_classes"])}
    cause_class = policy["cause_classes"][cause_code]
    band = _band_for(policy, status, delay_minutes)
    row = next((r for r in policy["rows"]
                if r["cause_class"] == cause_class and r["band"] == band), None)
    if row is None:
        return {"error": "No policy row for %s/%s" % (cause_class, band)}
    care = row["care"]

    meal = care["meal_usd"]
    if isinstance(meal, dict):
        need = meal["if_wait_minutes_for_alternative_gte"]
        if wait_minutes_for_alternative is None:
            meal_out = {"conditional": True, "if_wait_at_least_minutes": need, "amount_usd": meal["amount"]}
        else:
            meal_out = {"amount_usd": meal["amount"] if wait_minutes_for_alternative >= need
                        else meal.get("else", 0)}
    else:
        meal_out = {"amount_usd": meal}
    bonus = policy["loyalty_rules"].get(loyalty_tier or "Member", {})
    if meal_out["amount_usd"] and bonus.get("meal_bonus_usd"):
        meal_out["amount_usd"] = min(meal_out["amount_usd"] + bonus["meal_bonus_usd"],
                                     bonus.get("meal_bonus_cap_usd", 10**6))

    hotel = care["hotel"]
    if hotel.get("eligible") == "if_overnight":
        hotel_out = {"eligible": bool(overnight)}
        if overnight:
            hotel_out.update(nightly_cap_usd=hotel["nightly_cap_usd"], nights=hotel["nights"],
                             approval=hotel["approval"])
    else:
        hotel_out = {k: v for k, v in hotel.items() if k in ("eligible", "instead")}

    ground = care["ground_usd"]
    if isinstance(ground, dict) and "if_overnight" in ground:
        ground_out = {"amount_usd": ground["if_overnight"] if overnight else ground["else"]}
    else:
        ground_out = ground if isinstance(ground, dict) else {"amount_usd": ground}

    return {"source": "disruption_policy.json v%s" % policy["version"], "cause_class": cause_class,
            "band": band, "meal": meal_out, "hotel": hotel_out, "ground": ground_out,
            "note": "Informational. Refer to it as a credit or voucher, never a guarantee."}


def cause_in_plain_words(cause_code, language="en"):
    """Customer-safe wording for a cause code, from cause_labels_customer."""
    policy = load_policy()
    labels = policy["cause_labels_customer"].get(cause_code)
    if not labels:
        return {"error": "cause_code must be one of %s" % sorted(policy["cause_labels_customer"])}
    cls = policy["cause_classes"][cause_code]
    return {"cause_code": cause_code, "label": labels.get(language, labels["en"]),
            "language": language if language in labels else "en",
            "within_our_control": cls == "controllable",
            "note": "Name the cause only with this label. Do not elaborate or assign blame."}


EXTRA_TOOLS: List[Dict[str, Any]] = [   # ✏️ Build 2, step 2.1: schemas for the tools you add
    {
        "name": "care_entitlements",
        "description": (
            "Answer a general 'do I get a meal, hotel or ground transport while I wait?' "
            "question from Larkspur's care policy table (Handbook section 6). Needs no "
            "booking: pass the cause_code and status from get_flight_status, plus "
            "delay_minutes. Returns only the meal, hotel and ground-transport care for "
            "that situation, with conditions such as overnight or wait time. It is "
            "informational and cites no policy_row_id; it does not cover rebooking, "
            "refunds or goodwill, and never issues anything. Use check_policy for the "
            "full decision on a booking before issuing a voucher."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cause_code": {"type": "string", "enum": ["WX", "ATC", "MX", "CREW", "SEC"],
                               "description": "Cause from get_flight_status, never inferred from customer text."},
                "status": {"type": "string", "enum": ["ON_TIME", "DELAYED", "CANCELLED", "DIVERTED"],
                           "description": "Flight status from get_flight_status."},
                "delay_minutes": {"type": "integer",
                                  "description": "Departure delay in minutes. Use 0 for CANCELLED or DIVERTED."},
                "overnight": {"type": "boolean",
                              "description": "True if the customer is stranded overnight away from their home airport."},
                "wait_minutes_for_alternative": {"type": "integer",
                                                 "description": "Minutes until the chosen alternative departs. Omit if none chosen yet."},
                "loyalty_tier": {"type": "string", "enum": ["Member", "Silver", "Gold", "Summit"],
                                 "description": "From the booking; Gold and Summit get a larger meal credit."},
            },
            "required": ["cause_code", "status"],
        },
    },
    {
        "name": "cause_in_plain_words",
        "description": (
            "Turn a cause code into the wording Larkspur allows for customers, for "
            "questions like 'why was my flight cancelled?'. Pass the cause_code from "
            "get_flight_status. Returns the approved customer label (e.g. 'weather') and "
            "whether it was within Larkspur's control. Use only this label when naming "
            "a cause; never elaborate or blame anyone. Does not look up a flight or a policy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cause_code": {"type": "string", "enum": ["WX", "ATC", "MX", "CREW", "SEC"],
                               "description": "Cause from get_flight_status."},
                "language": {"type": "string", "enum": ["en", "es"],
                             "description": "Customer's language from the booking. Defaults to en."},
            },
            "required": ["cause_code"],
        },
    },
]
LOCAL_TOOLS: Dict[str, Any] = {          # ✏️ Build 2, step 2.1: the functions behind them
    "care_entitlements": care_entitlements,
    "cause_in_plain_words": cause_in_plain_words,
}


def text_of(response) -> str:
    """Given. The last non-empty text block, never content[0]."""
    texts = [b.text for b in response.content if getattr(b, "type", None) == "text" and b.text]
    return texts[-1] if texts else ""


def tool_results(response) -> List[Dict[str, Any]]:
    """Given. Runs every tool_use block and packages the results the way the
    API expects them back. A tool can live in three places: the MCP server,
    LOCAL_TOOLS, or support/tools.py."""
    # three branches, no try/except in this file: mcp_client.call_remote() and
    # support.call_local() answer with an error dict instead of raising, and both
    # record what came back on the trace
    results = []
    for block in response.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        if block.name in mcp_client.tool_names:
            output = mcp_client.call_remote(block.name, block.input)
        elif block.name in LOCAL_TOOLS:
            output = call_local(LOCAL_TOOLS[block.name], block.name, block.input)
        else:
            output = execute_tool(block.name, block.input)
        results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": str(output),
        })
    return results


def run_agent(pnr: str, last_name: str, message: str) -> str:            # ✏️ Build 1, step 1.2
    """Run the tool loop until Claude stops asking for tools. Return its final text."""
    client, tracer = new_session()
    tools = tool_list()
    messages = [
        {"role": "user", "content": f"PNR {pnr}, last name {last_name}. {message}"},
    ]

    response = client.messages.create(
        model=MODEL, max_tokens=4096, system=runtime_preamble() + SYSTEM_PROMPT + TONE_ADDENDUM,
        thinking={"type": "adaptive"}, tools=tools, messages=messages,
    )

    answer = ""
    turns = 1
    while response.stop_reason == "tool_use" and turns < MAX_TOOL_CALLS:
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results(response)})
        answer = text_of(response)
        response = client.messages.create(
            model=MODEL, max_tokens=4096, system=runtime_preamble() + SYSTEM_PROMPT + TONE_ADDENDUM,
            thinking={"type": "adaptive"}, tools=tools, messages=messages,
        )
        turns += 1

    return text_of(response)


def tool_list() -> List[Dict[str, Any]]:                   # ✏️ Build 2, step 2.2
    """Given. Exactly what Claude is offered on every turn; run.py --show-tools
    prints this list."""
    return build_tools() + mcp_client.tools() + EXTRA_TOOLS


# ──────────────────────────────────────────────────────────────────────────────
# Below this line: what Claude is told about each tool. Step 1.3.
# The functions these describe are written and correct, in support/tools.py.
# ──────────────────────────────────────────────────────────────────────────────
def build_tools() -> List[Dict[str, Any]]:                 # ✏️ Build 1, step 1.3
    """Anthropic-shaped schemas: name, description, input_schema. What Claude is
    told about each of the nine tools, and all it is ever told."""
    return [
        {
            "name": "lookup_booking",
            "description": (
                "Retrieve a Larkspur reservation from Altura by confirmation code (PNR) "
                "and the passenger's last name. Both are required to prevent a lookup on "
                "a guessed PNR. Returns fare family, loyalty tier, the segment that needs "
                "attention, and any group/partner/minor/SSR flags relevant to scope."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"pnr": {"type": "string"}, "last_name": {"type": "string"}},
                "required": ["pnr", "last_name"],
            },
        },
        {
            "name": "get_flight_status",
            "description": (
                "Look up a Larkspur or Larkspur Link flight's current OpsFeed status for "
                "one local date: status, delay minutes, and cause. Use this before telling "
                "a customer anything about a flight's timing; never state it from memory."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "flight_no": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["flight_no", "date"],
            },
        },
        {
            "name": "search_alternatives",
            "description": (
                "List the rebooking options Larkspur can offer for the disrupted flight on "
                "a booking: ranked alternative flights on the same route and cabin, each "
                "with an option_id, the flight(s), the date and seat availability for the "
                "number of passengers on the booking. Use it once lookup_booking and "
                "get_flight_status show the flight is cancelled, badly delayed or the "
                "connection is missed, and before offering the customer any alternative. "
                "Needs only the PNR. The option_id it returns is what hold_seat takes; never "
                "invent an option or its times. It does not hold or book anything, and it "
                "leaves out the original flight."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {
                        "type": "string",
                        "description": "The booking's confirmation code (PNR). The last name is not needed.",
                    },
                },
                "required": ["pnr"],
            },
        },
        {
            "name": "check_policy",
            "description": (
                "Resolve what Larkspur owes this customer for the disruption: rebooking "
                "waiver, refund path, meal/hotel/ground care, goodwill eligibility and cap, "
                "and any escalation triggers. cause_code, delay_minutes and status describe "
                "what get_flight_status told you; fare_family, loyalty_tier and whether this "
                "is overnight are looked up from the booking, not asked of you. Every "
                "response carries a policy_row_id. Cite it if you reference this decision "
                "again."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {"type": "string"},
                    "cause_code": {"type": "string", "enum": ["WX", "ATC", "MX", "CREW", "SEC"]},
                    "delay_minutes": {"type": "integer"},
                    "status": {"type": "string", "enum": ["ON_TIME", "DELAYED", "CANCELLED", "DIVERTED"]},
                    "wait_minutes_for_alternative": {"type": "integer"},
                    "chosen_option_id": {"type": "string"},
                },
                "required": ["pnr", "cause_code", "delay_minutes", "status"],
            },
        },
        {
            "name": "hold_seat",
            "description": "Place a 15-minute hold on one alternative. Reversible. It simply expires.",
            "input_schema": {
                "type": "object",
                "properties": {"option_id": {"type": "string"}, "pnr": {"type": "string"}},
                "required": ["option_id", "pnr"],
            },
        },
        {
            "name": "confirm_rebooking",
            "description": (
                "Finalize a held seat. Irreversible. Requires a confirmation_token that "
                "only the customer's own Confirm-click can produce. You cannot supply it "
                "yourself, and 'the customer said yes' in chat does not substitute for it."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"hold_id": {"type": "string"}, "confirmation_token": {"type": "string"}},
                "required": ["hold_id", "confirmation_token"],
            },
        },
        {
            "name": "issue_voucher",
            "description": (
                "Issue a meal, ground, hotel, or goodwill voucher. Auto-approves within the "
                "policy's threshold for that type; above it, returns a pending status for a "
                "human. It does not fail. Always pass the policy_row_id that made it eligible."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "voucher_type": {"type": "string", "enum": ["meal", "ground", "hotel", "goodwill"]},
                    "amount_usd": {"type": "number"},
                    "pnr": {"type": "string"},
                    "policy_row_id": {"type": "string"},
                },
                "required": ["voucher_type", "amount_usd", "pnr", "policy_row_id"],
            },
        },
        {
            "name": "escalate_to_human",
            "description": (
                "Hand this conversation to a human, with your reasoning attached. Use for "
                "groups, partner segments, unaccompanied minors, refunds, or anything else "
                "out of scope. This is the correct outcome for those cases, not a failure."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {"type": "string"}, "reason": {"type": "string"},
                    "summary_for_human": {"type": "string"}, "queue": {"type": "string"},
                },
                "required": ["pnr", "reason", "summary_for_human"],
            },
        },
        {
            "name": "send_confirmation",
            "description": "Send the customer a written confirmation of what was just done. Benign.",
            "input_schema": {
                "type": "object",
                "properties": {"pnr": {"type": "string"}, "message": {"type": "string"}},
                "required": ["pnr", "message"],
            },
        },
    ]