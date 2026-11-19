# PITCH.md

Six lines and a lever. Your words. The last two are scored.

Built: A disruption-care chat agent for Larkspur on nine given tools plus one we added over MCP (next_available_day), driven by our own loop in agent.py, capped at 8 tool turns before a human takes over.
Does: Reads the booking, checks the live flight status, finds real alternatives, looks up what Larkspur owes the customer under policy, and holds a seat. It never invents a flight, a time or a policy.
Number: About $0.07 of model cost for one cancelled-flight ticket (K7PQ2M: 4 turns, 5 tool calls, 18,169 tokens in, 1,093 out), against $6.90 for a human contact. One ticket, model cost only, no caching yet, and no bench run, so this is an estimate, not a measurement.
Safety check: confirm_rebooking cannot run without a token that only the customer's own Confirm click produces, so "yes" in chat never books anything. Holds expire on their own, and groups, partner segments, minors and refunds go to escalate_to_human.
Next: Run bench.py before and after our lever to replace the estimate with a measured cost, write our eval cases, and clear gate 1.4.
Still broken: An abusive customer (R8KD3F) gets the same calm, routine resolution with no tone handling, because TONE_ADDENDUM is still empty. Gates 1.4, 3.1 and 4.1 are not cleared and we have no eval cases of our own yet.
Lever: intelligence

## Priya asked

Costs: About $0.07 of model cost per ticket on our one traced run, about 1% of the $6.90 a human contact costs. That is model cost only: Larkspur's loaded figure is about 40% higher, and the humans still take 42% of chats, so the saving is smaller than the headline ratio. We will quote a measured number after bench.py.
Wrong: The agent can still say something untrue. Flight facts come from a tool call, never from memory, and every policy answer carries a policy_row_id we can check. We find errors by reading the trace and running our eval cases (not written yet). When it is wrong or unsure, the customer is handed to a human with the agent's reasoning attached, and nothing irreversible happens without the customer's own click.
Runs it: Not decided, and it needs a name before we leave. We propose a Larkspur contact-center operations lead who reads the traces and escalations weekly, with a policy owner who updates the policy table and tool descriptions when Handbook v14 changes. The eval cases and bench.py are the handover kit.
Left out: Voice (the scope is chat only). Group bookings, partner segments, unaccompanied minors and refunds, which go to a human by design. Tone handling for abusive customers (intelligence lever, not built yet). Live connections to Altura and OpsFeed: everything ran on a frozen copy of the data.
