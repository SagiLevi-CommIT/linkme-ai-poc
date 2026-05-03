resource "aws_memorydb_subnet_group" "this" {
  count = local.enable_memorydb ? 1 : 0

  name       = "mdb-subnet-${var.project_name}-${var.env}-redis"
  subnet_ids = var.private_db_subnet_ids

  tags = {
    Name        = "mdb-subnet-${var.project_name}-${var.env}-redis"
    Description = "MemoryDB subnet group for Phase 2 semantic cache"
  }
}

resource "aws_memorydb_parameter_group" "this" {
  count = local.enable_memorydb ? 1 : 0

  # Bumped to v2 so TF creates a fresh PG with search-enabled=yes from the start
  # (the parameter cannot be modified on an existing PG, and a cluster with
  # search disabled cannot be converted in place — both forced a recreation).
  name   = "mdb-pg-${var.project_name}-${var.env}-redis-search-v2"
  family = var.memorydb_config.parameter_group_family

  parameter {
    name  = "search-enabled"
    value = "yes"
  }

  parameter {
    name  = "search-query-timeout-ms"
    value = "10000"
  }

  tags = {
    Name        = "mdb-pg-${var.project_name}-${var.env}-redis-search-v2"
    Description = "MemoryDB parameter group for HNSW vector search"
  }
}

resource "aws_memorydb_cluster" "this" {
  count = local.enable_memorydb ? 1 : 0

  name     = "mdb-${var.project_name}-${var.env}-redis"
  acl_name = "open-access"

  node_type                  = var.memorydb_config.node_type
  num_shards                 = var.memorydb_config.num_shards
  num_replicas_per_shard     = var.memorydb_config.num_replicas_per_shard
  engine                     = "redis"
  engine_version             = var.memorydb_config.engine_version
  port                       = var.memorydb_config.port
  subnet_group_name          = aws_memorydb_subnet_group.this[0].name
  security_group_ids         = [aws_security_group.memorydb[0].id]
  parameter_group_name       = aws_memorydb_parameter_group.this[0].name
  tls_enabled                = true
  snapshot_retention_limit   = var.memorydb_config.snapshot_retention_limit
  maintenance_window         = var.memorydb_config.maintenance_window
  auto_minor_version_upgrade = true

  tags = {
    Name        = "mdb-${var.project_name}-${var.env}-redis"
    Description = "MemoryDB Redis 7.1+ semantic cache HNSW 768-dim for Phase 2"
  }
}
