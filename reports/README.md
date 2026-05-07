# Reports

Important files:

- `tex/paper_report.pdf`: generated IEEEtran conference-style paper PDF
- `tex/paper_report.tex`: IEEEtran conference-style paper source
- `report.md`: final Markdown project report and summary for submission
- `[Tuan Minh Pham]_[Report].pptx`: project presentation deck
- `Template.pptx`: original course presentation template

Assets:

- `diagrams/runtime_architecture.drawio.png`: runtime service architecture
- `diagrams/flowchart.drawio.png`: feature and label-building flow
- `diagrams/aws_deployment_containers.drawio.png`: AWS container deployment view
- `pictures/feature_importance.png`: model feature-importance figure

Reference material:

- `../docs/architecture.md`: implementation architecture notes
- `../docs/feature_definitions.md`: feature dictionary
- `../docs/data_contracts.md`: runtime data contracts
- `../docs/deployment.md`: deployment notes
- `../docs/aws_ec2_vs_fargate_comparison.md`: EC2 vs Fargate comparison appendix

Code references:

- `../backend/`: C++ market-data, feature, inference, and strategy runtime
- `../ml_pipeline/`: Python data, training, evaluation, and serving pipeline
- `../frontend/electron/`: operator UI
- `../deploy/`: Docker, ECS, EC2, and Terraform deployment assets

Submission package:

Run `../scripts/prepare_submission.sh` from the repository root to create a clean zip in `submission/`.
