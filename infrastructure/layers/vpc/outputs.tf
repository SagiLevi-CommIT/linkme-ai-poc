output "nat_gateway_id" {
  description = "ID of the NAT gateway"
  value       = aws_nat_gateway.this.id
}

output "private_app_subnet_1_id" {
  description = "ID of private application subnet in AZ1"
  value       = aws_subnet.private_app_1.id
}

output "private_app_subnet_2_id" {
  description = "ID of private application subnet in AZ2"
  value       = aws_subnet.private_app_2.id
}

output "private_app_subnet_ids" {
  description = "List of private application subnet IDs"
  value       = [aws_subnet.private_app_1.id, aws_subnet.private_app_2.id]
}

output "private_db_subnet_1_id" {
  description = "ID of private database subnet in AZ1"
  value       = aws_subnet.private_db_1.id
}

output "private_db_subnet_2_id" {
  description = "ID of private database subnet in AZ2"
  value       = aws_subnet.private_db_2.id
}

output "private_db_subnet_ids" {
  description = "List of private database subnet IDs"
  value       = [aws_subnet.private_db_1.id, aws_subnet.private_db_2.id]
}

output "public_subnet_1_id" {
  description = "ID of public subnet in AZ1"
  value       = aws_subnet.public_1.id
}

output "public_subnet_2_id" {
  description = "ID of public subnet in AZ2"
  value       = aws_subnet.public_2.id
}

output "public_subnet_ids" {
  description = "List of public subnet IDs"
  value       = [aws_subnet.public_1.id, aws_subnet.public_2.id]
}

output "vpc_cidr" {
  description = "CIDR block of the VPC"
  value       = aws_vpc.this.cidr_block
}

output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.this.id
}
