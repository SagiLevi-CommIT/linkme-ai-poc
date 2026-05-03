"""EKS-hosted Messages Pusher.

Reads a set of JSONL batch files from the simulator input bucket
(`s3://<input-messages>/messages/{run_id}/batch-*.jsonl`) and pushes
every line onto the Incoming SQS queue using `send_message_batch`.
"""
