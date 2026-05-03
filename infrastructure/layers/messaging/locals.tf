locals {
  enable_messaging = var.enable_messaging
  enable_memorydb  = var.enable_messaging && var.enable_memorydb
}
