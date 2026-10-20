import { defineRailway, github, project, service } from "railway/iac";
// This repository manages only its own resources in the environment. Other
// repositories export their own partial name.
// See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
export const partial = "proyecto_API_legal";
export default defineRailway(() => {
  const proyecto_API_legal = service("proyecto_API_legal", {
    source: github("martin180921/proyecto_API_legal", { branch: "main", checkSuites: false }),
    build: { buildCommand: "", buildEnvironment: "V3", builder: "RAILPACK" },
    start: "uvicorn app.main:app --host 0.0.0.0 --port $PORT",
    healthcheck: "/v1/health/ready",
    healthcheckTimeout: 60,
    preDeploy: "alembic upgrade head",
    replicas: { "sfo": 1 },
    networking: { privateNetworkEndpoint: "proyectoapilegal" },
  });

  return project("proyecto_API_legal", {
    variables: { managed: false },
    resources: [proyecto_API_legal],
  });
});
