from personal_agent_eval.artifacts import RunArtifact
from personal_agent_eval.artifacts.run_artifact import FinalOutputTraceEvent


def check_output(artifact: RunArtifact) -> dict[str, object]:
    final_outputs = [
        event.content
        for event in artifact.trace
        if isinstance(event, FinalOutputTraceEvent) and event.content is not None
    ]
    return {
        "passed": bool(final_outputs),
        "outputs": {"final_output_count": len(final_outputs)},
    }
