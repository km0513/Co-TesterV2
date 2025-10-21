#!/bin/bash
# Script to check pod logs and status

echo "=== Getting pod status ==="
kubectl --kubeconfig /home/ec2-user/files/eks-kubectl-kh-dev.conf get pods -n dev-prism-app -l app=dev-upgrad-co-tester

echo -e "\n=== Getting recent pod logs ==="
kubectl --kubeconfig /home/ec2-user/files/eks-kubectl-kh-dev.conf logs -n dev-prism-app -l app=dev-upgrad-co-tester --tail=100

echo -e "\n=== Getting pod events ==="
kubectl --kubeconfig /home/ec2-user/files/eks-kubectl-kh-dev.conf get events -n dev-prism-app --sort-by='.lastTimestamp' | grep upgrad-co-tester | tail -20

echo -e "\n=== Describing latest pod ==="
POD_NAME=$(kubectl --kubeconfig /home/ec2-user/files/eks-kubectl-kh-dev.conf get pods -n dev-prism-app -l app=dev-upgrad-co-tester -o jsonpath='{.items[0].metadata.name}')
kubectl --kubeconfig /home/ec2-user/files/eks-kubectl-kh-dev.conf describe pod $POD_NAME -n dev-prism-app
