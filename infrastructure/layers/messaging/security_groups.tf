resource "aws_security_group" "memorydb" {
  count = local.enable_memorydb ? 1 : 0

  name        = "sgr-${var.project_name}-${var.env}-memorydb"
  description = "MemoryDB cluster SG workloads layer adds ingress from task SG"
  vpc_id      = var.vpc_id

  tags = {
    Name        = "sgr-${var.project_name}-${var.env}-memorydb"
    Description = "MemoryDB Redis access control"
  }
}
