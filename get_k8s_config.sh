#!/bin/bash
# Get the actual deployment configuration

echo "=== Current Deployment Config ==="
kubectl --kubeconfig /home/ec2-user/files/eks-kubectl-kh-dev.conf get deployment dev-upgrad-co-tester -n dev-prism-app -o yaml
