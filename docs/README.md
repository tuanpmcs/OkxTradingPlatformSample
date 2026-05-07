# OKX Pulse Documentation

This folder contains the reviewer-facing technical documentation for the project. The final report lives in `../reports/report.md`; these files provide the supporting implementation detail.

## Reading Order

| File | Purpose |
| --- | --- |
| `architecture.md` | System components, online runtime flow, and offline training flow |
| `data_contracts.md` | gRPC and CSV contracts shared by the runtime, model server, and training data |
| `feature_engineering_hft.md` | HFT market-data concepts and executable-PnL label logic |
| `feature_definitions.md` | Feature groups used by the C++ runtime and Python training pipeline |
| `deployment.md` | Local Docker, AWS ECS/EC2, and operational deployment notes |
| `aws_ec2_vs_fargate_comparison.md` | Benchmark and cost comparison appendix |
| `aws_hft_course_project.md` | Course requirement mapping and demo checklist |
| `mainpage.md` | Doxygen landing page source |

## Diagrams

Diagrams are stored in `diagrams/` and are referenced by both docs and reports:

- `diagrams/runtime_architecture.drawio.png`
- `diagrams/flowchart.drawio.png`
- `diagrams/aws_deployment_containers.drawio.png`
- `diagrams/grouped_workers.png`

## Generated Docs

Generate Doxygen HTML output from the repository root:

```bash
bash docs/generate.sh
```

The generated site is written to `docs/build/html/` and is excluded from submission packages.
