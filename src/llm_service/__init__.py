"""EKS-hosted LLM Service.

Long-running SQS FIFO consumer that reads BatchQueueItems off the
AI Processing queue (grouped by lead_id), performs KB retrieval + LLM
invocation, and writes final answers to the Results DynamoDB table.
Also updates the exact cache and MemoryDB semantic cache for future
hits.
"""
