"""AgentDesk Streamlit application."""

import html
from uuid import uuid4

import streamlit as st

from agentdesk.agents.langchain_adapter import LangChainModelClient
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
if "active_node" not in st.session_state:
    st.session_state.active_node = ""


def render_mermaid(diagram: str, *, height: int = 560) -> None:
    st.iframe(
        f"""
        <div class="mermaid">{html.escape(diagram)}</div>
        <script type="module">
          import mermaid from
            'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
          mermaid.initialize({{ startOnLoad: false, theme: 'dark' }});
          await mermaid.run({{ querySelector: '.mermaid' }});
        </script>
        """,
        height=height,
        width="stretch",
        alt="AgentDesk LangGraph architecture",
    )


preview_connection = connect(settings.database_path)
preview_supervisor = Supervisor(Repository(preview_connection), settings)
preview_mermaid = preview_supervisor.mermaid(st.session_state.active_node or None)
preview_connection.close()

graph_placeholder = st.sidebar.empty()


def show_graph(diagram: str) -> None:
    with graph_placeholder.container():
        st.subheader("Live LangGraph")
        if st.session_state.active_node:
            st.caption(f"Active node: {st.session_state.active_node}")
        render_mermaid(diagram)


show_graph(preview_mermaid)

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
    supervisor_ref: dict[str, Supervisor] = {}

    def on_node(node: str) -> None:
        st.session_state.active_node = node
        if runtime := supervisor_ref.get("runtime"):
            show_graph(runtime.mermaid(node))

    supervisor = Supervisor(
        Repository(connection),
        settings,
        live_call=(
            LangChainModelClient(settings)
            if settings.llm_mode == LLMMode.RECORD
            else None
        ),
        on_node=on_node,
    )
    supervisor_ref["runtime"] = supervisor
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
