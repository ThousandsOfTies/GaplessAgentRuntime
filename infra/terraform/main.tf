terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  description = "AWS region"
  default     = "ap-southeast-2"
}

variable "instance_type" {
  description = "EC2 instance type (ARM64)"
  default     = "t4g.small"
}

variable "key_name" {
  description = "SSH key pair name"
}

variable "ami_id" {
  description = "Ubuntu ARM64 AMI ID (Ubuntu 24.04 LTS, arm64)"
  # ap-southeast-2: Ubuntu 24.04 LTS arm64 — 更新時は `aws ec2 describe-images` で最新を確認
  default = "ami-0f5d1713c9af4fe30"
}

# ──────────────────────────────────────────────
# Security Group
# ──────────────────────────────────────────────
resource "aws_security_group" "gar_sim" {
  name        = "gar-sim"
  description = "Gapless Agent Runtime simulation host"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ──────────────────────────────────────────────
# EC2 Instance
# ──────────────────────────────────────────────
resource "aws_instance" "gar_sim" {
  ami                    = var.ami_id
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.gar_sim.id]

  user_data = file("${path.module}/user_data.sh")

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  tags = {
    Name    = "gar-sim"
    Project = "GaplessAgentRuntime"
  }
}

# ──────────────────────────────────────────────
# Outputs
# ──────────────────────────────────────────────
output "instance_id" {
  value = aws_instance.gar_sim.id
}

output "public_ip" {
  value = aws_instance.gar_sim.public_ip
}
