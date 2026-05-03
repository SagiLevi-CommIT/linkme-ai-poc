"""EKS-hosted Cache Service.

Long-running SQS consumer that reads from the Incoming queue,
performs the three-tier cache lookup (exact DDB, semantic MemoryDB),
and either writes a result directly to the Results table or hands off
to the AI Processing FIFO queue for LLM processing.
"""
