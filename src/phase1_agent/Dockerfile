FROM --platform=linux/arm64 python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ../common/ ./common/
COPY ../batch_llm/ ./batch_llm/
COPY . ./phase1_agent/

ENV PYTHONPATH=/app

EXPOSE 8080 8000

CMD ["python", "-m", "phase1_agent.agentcore_agent"]
