# AgentCore agent runtime image — provides uvx + the two awslabs MCP servers.
#
# All four agents (security_analyzer, crawler, property_analyzer,
# guard_rule_generator) share this image. The agentcore CLI sets the per-agent
# entrypoint at deploy time, so the CMD here is a no-op default — agentcore
# overrides it with `python <entrypoint>.py` for each runtime.
#
# Why this image and not Direct Code Deploy: each agent uses MCPClient with
# stdio_client(StdioServerParameters(command="uvx", ...)) to spawn the awslabs
# MCP servers. That requires `uvx` on PATH, which the default Python runtime
# does not include. This base image (uv on Python 3.11) provides uvx natively.

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# Build tools needed during MCP-server install (cfn-guard depends on Rust-built
# crates; awslabs.aws-iac-mcp-server bundles them via uv tool install).
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc build-essential && \
    rm -rf /var/lib/apt/lists/*

# Pre-install both awslabs MCP servers so uvx doesn't have to fetch them on
# every cold start. Pinning to @latest matches the in-code StdioServerParameters
# args, so this image stays fresh across rebuilds.
RUN uv tool install awslabs.aws-documentation-mcp-server@latest && \
    uv tool install awslabs.aws-iac-mcp-server@latest

# Strip build tools to keep the image lean — the installed CLIs are now binaries.
RUN apt-get purge -y gcc build-essential && apt-get autoremove -y

# Python deps: bedrock-agentcore + strands + mcp client + pydantic.
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Copy all agent source files. agentcore CLI will set the actual CMD per-agent
# at deploy time via --entrypoint flag.
COPY . .

EXPOSE 8080

# Default — overridden per-agent by agentcore deploy.
CMD ["python", "security_analyzer_agent.py"]
