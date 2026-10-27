"""Integration coverage for the compiled LangGraph workflow."""
from io import BytesIO

from graph import builder


def test_compiled_graph_routes_parallel_agents_through_review(monkeypatch):
    seen = []

    def manager_node(state):
        seen.append(("manager", state.get("iteration_count", 0)))
        return {
            "current_plan": {
                "platform_tasks": [{"platform": "x"}, {"platform": "linkedin"}]
            },
            "current_step": "manager",
            "task_completed": False,
        }

    def make_agent(platform):
        def agent(state):
            seen.append((platform, state["current_step"]))
            return {
                "latest_results": {
                    platform: {
                        "platform": platform,
                        "processed_content": f"{platform} draft",
                    }
                },
                "execution_history": [{"platform": platform}],
                "current_step": f"{platform}_drafted",
            }

        return agent

    def review(state):
        seen.append(("review", set(state["latest_results"])))
        return {
            "processed_content": [
                {"platform": platform, "processed_content": f"{platform} draft"}
                for platform in ("x", "linkedin")
            ],
            "task_completed": True,
            "task_failed": False,
            "replan_required": False,
            "current_step": "completed",
        }

    monkeypatch.setattr(builder, "manager_node", manager_node)
    monkeypatch.setattr(builder, "x_agent", make_agent("x"))
    monkeypatch.setattr(builder, "linkedin_agent", make_agent("linkedin"))
    monkeypatch.setattr(builder, "review_refine_node", review)

    result = builder.build_graph().invoke({"current_step": "start"})

    assert result["task_completed"] is True
    assert result["latest_results"] == {
        "x": {"platform": "x", "processed_content": "x draft"},
        "linkedin": {"platform": "linkedin", "processed_content": "linkedin draft"},
    }
    assert result["processed_content"] == [
        {"platform": "x", "processed_content": "x draft"},
        {"platform": "linkedin", "processed_content": "linkedin draft"},
    ]
    assert [entry[0] for entry in seen].count("review") == 1
    assert [entry[0] for entry in seen].count("manager") == 1


def test_graph_agent_wrapper_drops_parallel_current_step_updates():
    agent = builder._agent_without_step_update(
        lambda state: {"current_step": "agent", "execution_history": ["done"]}
    )

    assert agent({}) == {"execution_history": ["done"]}


def test_graph_image_writer_writes_rendered_bytes(monkeypatch):
    class Drawable:
        def draw_mermaid_png(self):
            return b"graph"

    saved = {}

    class OutputFile(BytesIO):
        def write(self, content):
            saved["contents"] = content
            return super().write(content)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def open_output(path, mode):
        saved["path"] = path
        saved["mode"] = mode
        saved["file"] = OutputFile()
        return saved["file"]

    def get_drawable():
        return Drawable()

    monkeypatch.setattr(builder.app_graph, "get_graph", get_drawable)
    monkeypatch.setattr(builder, "open", open_output, raising=False)

    builder.render_graph_image("graph.png")

    assert saved["path"] == "graph.png"
    assert saved["mode"] == "wb"
    assert saved["contents"] == b"graph"
    assert saved["file"].closed
