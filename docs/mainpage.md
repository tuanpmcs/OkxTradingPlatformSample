# OKX Pulse Docs

This is the Doxygen landing page for the OKX Pulse project. For the submission package, start with `README.md`, then use the files below as supporting technical notes.

1. [architecture.md](architecture.md): system layout and runtime flow
2. [data_contracts.md](data_contracts.md): gRPC and CSV interfaces
3. [feature_engineering_hft.md](feature_engineering_hft.md): bid/ask, order-book, trade-flow, PnL, and labeling explanation
4. [feature_definitions.md](feature_definitions.md): main runtime and training features
5. [deployment.md](deployment.md): local and AWS deployment summary
6. [aws_ec2_vs_fargate_comparison.md](aws_ec2_vs_fargate_comparison.md): benchmark checklist
7. [aws_hft_course_project.md](aws_hft_course_project.md): course requirement mapping

Report files:

- [../reports/README.md](../reports/README.md)
- [../reports/report.md](../reports/report.md)
- [../README.md](../README.md)

Generate HTML docs with:

```bash
bash docs/generate.sh
```
