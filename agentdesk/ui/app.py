"""AgentDesk Streamlit application."""

from uuid import uuid4

import streamlit as st

from agentdesk.agents.strands_adapter import StrandsModelClient
from agentdesk.agents.supervisor import Supervisor
from agentdesk.config import LLMMode, Settings
from agentdesk.db.connection import connect
from agentdesk.db.repository import Repository
from agentdesk.db.seed import seed_database
from agentdesk.runtime.replay import ReplayMissError
from agentdesk.schemas.agents import PolicySupervisorInput, SupervisorInput
from agentdesk.schemas.common import AgentContext


st.set_page_config(page_title="AgentDesk", page_icon="🧭", layout="wide")
settings = Settings()
if not settings.database_path.exists():
    seed_database(settings.database_path)

st.title("AgentDesk")
st.caption(
    "Autonomous multi-agent customer service, resolved end to end within policy guardrails."
)

if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = uuid4()
if "messages" not in st.session_state:
    st.session_state.messages = []
if "trace" not in st.session_state:
    st.session_state.trace = []

with st.sidebar:
    st.subheader("Live agent trace")
    st.caption(f"Mode: {settings.llm_mode.value.upper()}")
    if not st.session_state.trace:
        st.caption("No agent steps yet.")
    for event in st.session_state.trace:
        with st.expander(f"{event['agent']} · {event['event_type']}"):
            st.json(event)

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

with st.form("customer_request"):
    order_id = st.text_input("Order ID", value="ORD-0002")
    email = st.text_input(
        "Email", value="customer001@northwind.test", type="password"
    )
    customer_message = st.text_input(
        "Message", value="Where is my order?"
    )
    submitted = st.form_submit_button("Send")

if submitted:
    st.session_state.messages.append({"role": "user", "content": customer_message})
    connection = connect(settings.database_path)
    supervisor = Supervisor(
        Repository(connection),
        settings,
        live_call=(
            StrandsModelClient(settings) if settings.llm_mode == LLMMode.RECORD else None
        ),
    )
    try:
        context = AgentContext(
            conversation_id=st.session_state.conversation_id,
            turn_id=uuid4(),
            customer_message=customer_message,
        )
        policy_terms = {"policy", "refund limit", "return window", "price match"}
        if any(term in customer_message.lower() for term in policy_terms):
            result = supervisor.run_policy(PolicySupervisorInput(context=context))
        else:
            result = supervisor.run(
                SupervisorInput(
                    context=context,
                    order_id=order_id,
                    email=email,
                )
            )
        reply = result.final_reply
    except ReplayMissError:
        reply = (
            "This request has no replay fixture. Run the scenario in RECORD mode first."
        )
    finally:
        connection.close()
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.session_state.trace = [
        event.model_dump(mode="json") for event in supervisor.trace.events
    ]
    st.rerun()
