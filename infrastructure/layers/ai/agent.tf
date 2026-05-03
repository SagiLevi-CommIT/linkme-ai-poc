# ============================================================
# Bedrock Agent
# ============================================================

resource "aws_bedrockagent_agent" "this" {
  count = local.enable_agent ? 1 : 0

  agent_name                  = format(local.name_short, "agent")
  agent_resource_role_arn     = aws_iam_role.agent[0].arn
  foundation_model            = var.agent_foundation_model
  instruction                 = var.agent_instruction
  idle_session_ttl_in_seconds = var.agent_idle_session_ttl
  prepare_agent               = false

  tags = {
    Name        = format(local.name_short, "agent")
    Description = "Bedrock Agent for LinkMe AI - profile creation RAG and web tools"
  }
}

# Associate agent with Knowledge Base (conditional: both agent and KB enabled)
# Must be created before the prepare step and alias - associating a KB resets
# the agent to NOT_PREPARED, so PrepareAgent must be called afterwards.
resource "aws_bedrockagent_agent_knowledge_base_association" "this" {
  count = local.enable_agent && local.enable_knowledge_base ? 1 : 0

  agent_id             = aws_bedrockagent_agent.this[0].agent_id
  knowledge_base_id    = aws_bedrockagent_knowledge_base.this[0].id
  description          = "LinkMe AI Knowledge Base - profiles documents and RAG data"
  knowledge_base_state = "ENABLED"
}

# Explicitly prepare the agent after KB association.
# Required because: (a) prepare_agent=false on the agent resource avoids a race
# condition when KB association and agent creation happen in the same apply, and
# (b) associating a KB resets the agent to NOT_PREPARED - so we must call
# PrepareAgent here, after the association, before creating the alias.
resource "terraform_data" "prepare_agent" {
  count = local.enable_agent ? 1 : 0

  triggers_replace = concat(
    [aws_bedrockagent_agent.this[0].agent_id],
    aws_bedrockagent_agent_knowledge_base_association.this[*].knowledge_base_id,
  )

  provisioner "local-exec" {
    command = <<-EOT
      aws bedrock-agent prepare-agent \
        --agent-id ${aws_bedrockagent_agent.this[0].agent_id} \
        --region ${var.region}
      for i in $(seq 1 36); do
        status=$(aws bedrock-agent get-agent \
          --agent-id ${aws_bedrockagent_agent.this[0].agent_id} \
          --region ${var.region} \
          --query 'agent.agentStatus' \
          --output text)
        echo "Agent status: $status (attempt $i/36)"
        [ "$status" = "PREPARED" ] && exit 0
        sleep 10
      done
      echo "ERROR: Agent did not reach PREPARED state after 6 minutes"
      exit 1
    EOT
  }

  depends_on = [aws_bedrockagent_agent_knowledge_base_association.this]
}

# Stable alias for agent invocation - avoids referencing the mutable DRAFT version.
# Must wait for the explicit prepare step above.
resource "aws_bedrockagent_agent_alias" "this" {
  count = local.enable_agent ? 1 : 0

  agent_alias_name = "live"
  agent_id         = aws_bedrockagent_agent.this[0].agent_id

  tags = {
    Name        = format(local.name_fmt, "agent-alias", "live")
    Description = "Live alias for the LinkMe AI Bedrock Agent"
  }

  depends_on = [terraform_data.prepare_agent]
}
